"""Tests for the prototype attestation generator.

These cover the pure-Python path — the real Phala flow is exercised via
manual integration only (it requires a live CVM).
"""

from __future__ import annotations

import struct

from eth_account import Account
from eth_account.messages import _hash_eip191_message  # noqa: F401
from eth_keys import keys as eth_keys

from backend.agent.attestation import (
    QUOTE_LEN,
    TDX_ATT_KEY_TYPE_ECDSA_P256,
    TDX_QUOTE_VERSION,
    TEE_TYPE_TDX,
    generate_attestation,
)


def test_quote_has_required_header_constants():
    pk = "0x" + Account.create().key.hex()
    att = generate_attestation(agent_private_key=pk, mrtd_seed="seed-a")
    assert len(att.quote) == QUOTE_LEN

    version = struct.unpack_from("<H", att.quote, 0)[0]
    att_key_type = struct.unpack_from("<H", att.quote, 2)[0]
    tee_type = struct.unpack_from("<I", att.quote, 4)[0]

    assert version == TDX_QUOTE_VERSION
    assert att_key_type == TDX_ATT_KEY_TYPE_ECDSA_P256
    assert tee_type == TEE_TYPE_TDX


def test_report_data_is_embedded_in_quote():
    pk = "0x" + Account.create().key.hex()
    att = generate_attestation(agent_private_key=pk, mrtd_seed="seed-b")
    assert att.quote[0x230:0x250] == att.report_data
    assert len(att.report_data) == 32


def test_signature_recovers_to_attested_signer():
    pk = "0x" + Account.create().key.hex()
    att = generate_attestation(agent_private_key=pk, mrtd_seed="seed-c")
    assert len(att.report_data_sig) == 65

    # eth_keys recovers the public key from a raw signature over a 32-byte hash
    r = int.from_bytes(att.report_data_sig[0:32], "big")
    s = int.from_bytes(att.report_data_sig[32:64], "big")
    v = att.report_data_sig[64]
    if v >= 27:
        v -= 27
    sig = eth_keys.Signature(vrs=(v, r, s))
    recovered_pub = sig.recover_public_key_from_msg_hash(att.report_data)
    recovered_addr = recovered_pub.to_checksum_address()
    assert recovered_addr == att.attested_signer


def test_same_seed_and_key_produce_same_mrtd_but_different_report_data():
    pk = "0x" + Account.create().key.hex()
    a = generate_attestation(agent_private_key=pk, mrtd_seed="same")
    b = generate_attestation(agent_private_key=pk, mrtd_seed="same")
    # mrtd is deterministic on the seed
    assert a.mrtd_hex == b.mrtd_hex
    # report_data is randomised per call via the nonce
    assert a.report_data != b.report_data


def test_explicit_nonce_makes_attestation_deterministic():
    pk = "0x" + Account.create().key.hex()
    nonce = b"\x42" * 32
    a = generate_attestation(agent_private_key=pk, mrtd_seed="det", nonce=nonce)
    b = generate_attestation(agent_private_key=pk, mrtd_seed="det", nonce=nonce)
    assert a.report_data == b.report_data
    assert a.quote == b.quote
