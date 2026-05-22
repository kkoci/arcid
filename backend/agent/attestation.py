"""DCAP attestation quote handling.

In production: read the quote from `/dev/tdx_guest` (Linux TDX char device)
via Phala's `dstack-tdx-attest` helper. Output is the raw ~5 KB ECDSA-P256
DCAP v4 quote.

In prototype mode: generate a deterministic but structurally valid quote that
the simplified on-chain verifier accepts. The shape — header, mrtd, report
data layout, signature offsets — is identical to a real quote, so the same
code path drives both modes.

The signature returned is *NOT* the quote's own ECDSA cert-chain signature
(that requires Intel PCS). Instead it's the agent's signature over the
report-data field. The on-chain verifier uses it to prove that whoever
generated this quote also controls the key the agent now uses to interact
with Arc — closing the gap between hardware identity and Ethereum address.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from eth_account.messages import _hash_eip191_message  # noqa: F401  (kept for parity)
from eth_utils import keccak

from ..config import settings


# Intel TDX DCAP v4 constants — kept identical to the values the on-chain
# verifier checks. If these drift, the verifier rejects the quote.
TDX_QUOTE_VERSION = 4
TDX_ATT_KEY_TYPE_ECDSA_P256 = 2
TEE_TYPE_TDX = 0x00000081

QUOTE_LEN = 0x250  # minimal length our verifier requires


@dataclass
class Attestation:
    quote: bytes              # raw DCAP quote bytes
    report_data_sig: bytes    # 65-byte ECDSA over report_data, recoverable to attested_signer
    report_data: bytes        # 32-byte commitment embedded in the quote
    attested_signer: str      # 0x-prefixed checksum address
    mrtd_hex: str             # keccak256 of the 48-byte mrtd field, for display


def _build_mock_quote(mrtd: bytes, report_data: bytes) -> bytes:
    """Construct a v4-style buffer whose header, mrtd and report_data offsets
    match Intel's layout. Everything else is zero."""
    assert len(mrtd) == 48, "mrtd must be 48 bytes"
    assert len(report_data) == 32, "report_data prefix is 32 bytes"

    buf = bytearray(QUOTE_LEN)
    struct.pack_into("<H", buf, 0x00, TDX_QUOTE_VERSION)
    struct.pack_into("<H", buf, 0x02, TDX_ATT_KEY_TYPE_ECDSA_P256)
    struct.pack_into("<I", buf, 0x04, TEE_TYPE_TDX)
    buf[0x70:0xA0] = mrtd
    buf[0x230:0x250] = report_data
    return bytes(buf)


def generate_attestation(
    *,
    agent_private_key: str,
    mrtd_seed: str = "arcid-prototype-mrtd",
    nonce: Optional[bytes] = None,
) -> Attestation:
    """Produce an attestation the prototype verifier accepts.

    Args:
        agent_private_key: hex-prefixed secp256k1 key the agent holds inside the
            CVM. The recovered signer of `report_data_sig` is this key's address.
        mrtd_seed: stable string fed into keccak to fabricate a 48-byte mrtd
            measurement. In production this is the real TDX hardware measurement.
        nonce: optional 32-byte session nonce; falls back to fresh randomness.
    """
    if settings.use_real_phala:
        return _generate_real_attestation(agent_private_key=agent_private_key, nonce=nonce)

    if nonce is None:
        nonce = os.urandom(32)

    acct = Account.from_key(agent_private_key)

    # mrtd is 48 bytes; pad keccak (32) on the right with the first 16 bytes of
    # the seed-derived hash. Deterministic per seed.
    base = keccak(mrtd_seed.encode())
    mrtd = base + base[:16]

    # report_data commits to (signer_address ‖ nonce). The on-chain registry
    # uses the recovered signer + this commitment + mrtd to derive the agentId.
    report_data = keccak(bytes.fromhex(acct.address[2:]) + nonce)
    quote = _build_mock_quote(mrtd, report_data)

    # Sign the raw 32-byte digest (NOT EIP-191) so the verifier's ecrecover
    # works exactly the same on real and mock quotes.
    sig = _sign_raw_digest(acct, report_data)
    sig_bytes = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + sig.v.to_bytes(1, "big")

    return Attestation(
        quote=quote,
        report_data_sig=sig_bytes,
        report_data=report_data,
        attested_signer=acct.address,
        mrtd_hex="0x" + keccak(mrtd).hex(),
    )


def _sign_raw_digest(acct, digest: bytes):
    """eth_account renamed `signHash` → `unsafe_sign_hash` in 0.13; support both
    so we don't pin our test runs to a single point release."""
    if hasattr(acct, "unsafe_sign_hash"):
        return acct.unsafe_sign_hash(digest)
    return acct.signHash(digest)


def _generate_real_attestation(*, agent_private_key: str, nonce: Optional[bytes]) -> Attestation:
    """Real-mode path. Calls into Phala's TDX attestation helper.

    Imports are deferred so prototype-mode users do not need the system
    dependency (`dstack-tdx-attest`) installed.
    """
    # NOTE: This is intentionally a thin wrapper — the heavy lifting lives in
    # Phala's CVM image. If you are reading this in prototype mode, you can
    # safely ignore everything below.
    import httpx  # type: ignore

    acct = Account.from_key(agent_private_key)
    nonce = nonce or os.urandom(32)
    report_data = keccak(bytes.fromhex(acct.address[2:]) + nonce)

    resp = httpx.post(
        f"{settings.phala_cvm_endpoint}/attestation/quote",
        json={"report_data": report_data.hex()},
        headers={"Authorization": f"Bearer {settings.phala_cloud_api_key}"},
        timeout=30.0,
    )
    resp.raise_for_status()
    quote_hex = resp.json()["quote"]
    quote = bytes.fromhex(quote_hex.removeprefix("0x"))

    sig = _sign_raw_digest(acct, report_data)
    sig_bytes = sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + sig.v.to_bytes(1, "big")

    # The real mrtd is bytes 0x70-0xA0 of the quote
    mrtd = quote[0x70:0xA0]
    return Attestation(
        quote=quote,
        report_data_sig=sig_bytes,
        report_data=report_data,
        attested_signer=acct.address,
        mrtd_hex="0x" + keccak(mrtd).hex(),
    )
