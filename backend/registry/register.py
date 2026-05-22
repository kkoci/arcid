"""Registration orchestrator.

Public entry point: `register_agent(name, agent_private_key)`.

Steps:
  1. Generate a DCAP attestation (real on Phala TDX, mock otherwise).
  2. Submit the quote + signature to `ArcIDRegistry.register(...)` on Arc.
  3. Decode the emitted `AgentRegistered` event to get the canonical agentId.
  4. Provision a Circle Programmable Wallet for the agentId.
  5. Call `ArcIDRegistry.bindWallet(agentId, walletAddress)` as the registry
     operator so the wallet is reflected on-chain.

Each step is independently testable. If the on-chain RPC is not reachable
(e.g. nobody has run `npm run node`), the function raises with a clear
message rather than silently mocking — the on-chain trace is the value
proposition; we never fake it away.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from eth_account import Account
from eth_utils import keccak
from web3 import Web3

from ..agent.attestation import Attestation, generate_attestation
from ..config import settings
from .circle_wallets import CircleWallet, create_wallet_for_agent

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "contracts"


@dataclass
class RegistrationResult:
    agent_id: str
    attested_signer: str
    mrtd_hex: str
    wallet: CircleWallet
    tx_hash: str
    bind_tx_hash: Optional[str]
    gas_sponsored: bool
    name: str


# ----------------------------------------------------------------------------
# Web3 plumbing
# ----------------------------------------------------------------------------

def _load_abi(contract_name: str) -> list[dict[str, Any]]:
    """Read a compiled artifact ABI. Hardhat writes them to
    `artifacts/contracts/<file>.sol/<contract>.json`."""
    candidates = list(ARTIFACTS_DIR.rglob(f"{contract_name}.json"))
    if not candidates:
        raise RuntimeError(
            f"ABI for {contract_name} not found. Run `npm run compile` first."
        )
    artifact = json.loads(candidates[0].read_text())
    return artifact["abi"]


def _w3() -> Web3:
    w3 = Web3(Web3.HTTPProvider(settings.arc_rpc_url))
    if not w3.is_connected():
        raise RuntimeError(
            f"Could not reach Arc RPC at {settings.arc_rpc_url}. "
            "Start `npm run node` for local mode or set ARC_RPC_URL."
        )
    return w3


def _registry_contract(w3: Web3):
    if not settings.arcid_registry_address:
        raise RuntimeError(
            "ARCID_REGISTRY_ADDRESS not set. Deploy with `npm run deploy:local` first."
        )
    return w3.eth.contract(
        address=Web3.to_checksum_address(settings.arcid_registry_address),
        abi=_load_abi("ArcIDRegistry"),
    )


def _usdc_contract(w3: Web3):
    return w3.eth.contract(
        address=Web3.to_checksum_address(settings.usdc_token_address),
        abi=_load_abi("MockUSDC"),  # iface-compatible with real USDC for IERC20 calls
    )


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------

async def register_agent(
    name: str,
    *,
    agent_private_key: Optional[str] = None,
    operator_private_key: Optional[str] = None,
) -> RegistrationResult:
    """End-to-end registration. Returns the canonical record."""
    w3 = _w3()
    registry = _registry_contract(w3)

    # 1. Generate keys
    if agent_private_key is None:
        agent_private_key = "0x" + Account.create().key.hex()
    operator_private_key = operator_private_key or settings.deployer_private_key
    operator = Account.from_key(operator_private_key)

    # 2. Attestation
    attestation: Attestation = generate_attestation(agent_private_key=agent_private_key)

    # 3. (Optional) approve USDC for the registration fee. We try to approve
    #    enough for the fee in case the sponsored quota is exhausted; the
    #    contract is no-op safe when the quota is still available.
    fee = registry.functions.registrationFee().call()
    if fee > 0 and settings.usdc_token_address:
        try:
            usdc = _usdc_contract(w3)
            allowance = usdc.functions.allowance(operator.address, registry.address).call()
            if allowance < fee:
                nonce = w3.eth.get_transaction_count(operator.address)
                approve_tx = usdc.functions.approve(registry.address, fee * 100).build_transaction({
                    "from": operator.address,
                    "nonce": nonce,
                    "gas": 80_000,
                    "gasPrice": w3.eth.gas_price,
                    "chainId": settings.arc_chain_id,
                })
                signed = w3.eth.account.sign_transaction(approve_tx, operator.key)
                approve_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
                w3.eth.wait_for_transaction_receipt(approve_hash)
        except Exception as exc:  # USDC contract may not exist on real Arc until deploy
            logger.debug("USDC approve skipped: %s", exc)

    # 4. Submit register()
    nonce = w3.eth.get_transaction_count(operator.address)
    tx = registry.functions.register(
        attestation.quote, attestation.report_data_sig, name
    ).build_transaction({
        "from": operator.address,
        "nonce": nonce,
        "gas": 2_500_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.arc_chain_id,
    })
    signed = w3.eth.account.sign_transaction(tx, operator.key)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
    if receipt.status != 1:
        raise RuntimeError(f"register() reverted in tx {tx_hash.hex()}")

    # 5. Decode the AgentRegistered event for the canonical agentId
    events = registry.events.AgentRegistered().process_receipt(receipt)
    if not events:
        # Idempotent re-register doesn't emit; recompute from the attestation
        agent_id_bytes = keccak(
            _encode_abi(
                ["bytes32", "bytes32", "address"],
                [
                    bytes.fromhex(attestation.mrtd_hex.removeprefix("0x")),
                    attestation.report_data,
                    attestation.attested_signer,
                ],
            )
        )
        agent_id_hex = "0x" + agent_id_bytes.hex()
        gas_sponsored = False
    else:
        evt = events[0]["args"]
        agent_id_hex = "0x" + evt["agentId"].hex()
        gas_sponsored = bool(evt["gasSponsored"])

    # 6. Circle wallet
    wallet = await create_wallet_for_agent(agent_id_hex)

    # 7. Bind wallet on-chain (operator-only)
    bind_hash: Optional[str] = None
    try:
        bind_tx = registry.functions.bindWallet(
            bytes.fromhex(agent_id_hex.removeprefix("0x")),
            Web3.to_checksum_address(wallet.address),
        ).build_transaction({
            "from": operator.address,
            "nonce": w3.eth.get_transaction_count(operator.address),
            "gas": 120_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": settings.arc_chain_id,
        })
        signed_bind = w3.eth.account.sign_transaction(bind_tx, operator.key)
        bind_tx_hash = w3.eth.send_raw_transaction(signed_bind.raw_transaction)
        w3.eth.wait_for_transaction_receipt(bind_tx_hash)
        bind_hash = bind_tx_hash.hex()
    except Exception as exc:
        # Already-bound is the common case on idempotent re-registers
        logger.info("bindWallet skipped: %s", exc)

    return RegistrationResult(
        agent_id=agent_id_hex,
        attested_signer=attestation.attested_signer,
        mrtd_hex=attestation.mrtd_hex,
        wallet=wallet,
        tx_hash=tx_hash.hex(),
        bind_tx_hash=bind_hash,
        gas_sponsored=gas_sponsored,
        name=name,
    )


# ----------------------------------------------------------------------------
# read-side helpers (used by the leaderboard endpoint)
# ----------------------------------------------------------------------------

def list_agents(offset: int = 0, limit: int = 50) -> list[dict[str, Any]]:
    w3 = _w3()
    registry = _registry_contract(w3)
    page = registry.functions.listAgents(offset, limit).call()
    out: list[dict[str, Any]] = []
    for a in page:
        # a is a tuple matching the Agent struct order
        out.append({
            "agent_id": "0x" + a[0].hex(),
            "mrtd": "0x" + a[1].hex(),
            "report_data": "0x" + a[2].hex(),
            "attested_signer": a[3],
            "wallet": a[4],
            "name": a[5],
            "registered_at": int(a[6]),
            "gas_sponsored": bool(a[7]),
        })
    return out


def get_agent(agent_id_hex: str) -> dict[str, Any]:
    w3 = _w3()
    registry = _registry_contract(w3)
    a = registry.functions.getAgent(bytes.fromhex(agent_id_hex.removeprefix("0x"))).call()
    return {
        "agent_id": "0x" + a[0].hex(),
        "mrtd": "0x" + a[1].hex(),
        "report_data": "0x" + a[2].hex(),
        "attested_signer": a[3],
        "wallet": a[4],
        "name": a[5],
        "registered_at": int(a[6]),
        "gas_sponsored": bool(a[7]),
    }


# ----------------------------------------------------------------------------
# tiny ABI encoder so we can recompute agentId without web3.contract
# ----------------------------------------------------------------------------
def _encode_abi(types: list[str], values: list[Any]) -> bytes:
    from eth_abi import encode  # web3 transitive dep
    return encode(types, values)
