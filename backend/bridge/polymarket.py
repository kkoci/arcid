"""Polymarket V2 attribution bridge.

In real mode this wraps the V2 CLOB client and submits a limit order whose
`builderCode` field is the agent's ArcID. When the order fills, Polymarket
routes a portion of the venue fee to the address bound to that builder
code — for ArcID, that's the agent's Circle Programmable Wallet.

In prototype mode the bridge:
  - Registers the builder code on a locally-deployed `MockPolymarketBuilder`.
  - Returns a synthetic fill with a small USDC builder rebate that is paid
    from the operator's USDC stash, so the on-chain accumulation is real.
This lets the leaderboard show non-zero "fees earned" without depending on
real Polymarket testnet liquidity, which is unreliable inside a hackathon
window.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from eth_account import Account
from web3 import Web3

from ..config import settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "contracts"


@dataclass
class AttributedOrder:
    builder_code: str          # the agentId
    market_question: str
    side: str
    size_usdc: float
    fill_price: float
    builder_fee_usdc: float
    tx_hash: Optional[str]
    venue: str                 # "polymarket-v2" | "mock-builder"


def _load_abi(contract: str) -> list[dict[str, Any]]:
    candidates = list(ARTIFACTS_DIR.rglob(f"{contract}.json"))
    if not candidates:
        raise RuntimeError(f"ABI for {contract} not found. Run `npm run compile`.")
    return json.loads(candidates[0].read_text())["abi"]


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(settings.arc_rpc_url))


async def place_attributed_order(
    *,
    builder_code: str,
    fee_recipient: str,
    market_question: str,
    side: str,
    size_usdc: float,
) -> AttributedOrder:
    """Place an order attributed to `builder_code`."""
    if settings.use_real_polymarket:
        return await _place_real(
            builder_code=builder_code,
            market_question=market_question,
            side=side,
            size_usdc=size_usdc,
        )
    return _place_mock(
        builder_code=builder_code,
        fee_recipient=fee_recipient,
        market_question=market_question,
        side=side,
        size_usdc=size_usdc,
    )


# ----------------------------------------------------------------------------
# mock path — uses MockPolymarketBuilder on the local Hardhat node
# ----------------------------------------------------------------------------

def _place_mock(
    *,
    builder_code: str,
    fee_recipient: str,
    market_question: str,
    side: str,
    size_usdc: float,
) -> AttributedOrder:
    builder_addr = settings.polymarket_builder_address
    if not builder_addr or not settings.usdc_token_address:
        # No on-chain builder available; return a pure synthetic record so the
        # leaderboard still shows something.
        return AttributedOrder(
            builder_code=builder_code,
            market_question=market_question,
            side=side,
            size_usdc=size_usdc,
            fill_price=0.5,
            builder_fee_usdc=round(size_usdc * 0.01, 4),
            tx_hash=None,
            venue="synthetic",
        )

    w3 = _w3()
    operator = Account.from_key(settings.deployer_private_key)
    builder = w3.eth.contract(
        address=Web3.to_checksum_address(builder_addr),
        abi=_load_abi("MockPolymarketBuilder"),
    )
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(settings.usdc_token_address),
        abi=_load_abi("MockUSDC"),
    )
    builder_code_bytes = bytes.fromhex(builder_code.removeprefix("0x"))
    fee_recipient_addr = Web3.to_checksum_address(fee_recipient)

    # 1. Ensure the builder code is registered to the agent's wallet.
    current = builder.functions.feeRecipientOf(builder_code_bytes).call()
    if int(current, 16) == 0:
        tx = builder.functions.registerBuilder(builder_code_bytes, fee_recipient_addr).build_transaction({
            "from": operator.address,
            "nonce": w3.eth.get_transaction_count(operator.address),
            "gas": 120_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": settings.arc_chain_id,
        })
        signed = w3.eth.account.sign_transaction(tx, operator.key)
        h = w3.eth.send_raw_transaction(signed.raw_transaction)
        w3.eth.wait_for_transaction_receipt(h)

    # 2. Simulate a fill — 1% builder rebate on notional.
    fee_units = int(round(size_usdc * 0.01 * 1_000_000))  # USDC has 6 decimals
    # Make sure the "Polymarket router" (the operator EOA here) has USDC + allowance.
    balance = usdc.functions.balanceOf(operator.address).call()
    if balance < fee_units:
        try:
            usdc.functions.mint(operator.address, fee_units).transact({"from": operator.address})
        except Exception:
            # Real USDC has no mint; the operator must already be funded.
            pass

    allowance = usdc.functions.allowance(operator.address, builder.address).call()
    if allowance < fee_units:
        approve = usdc.functions.approve(builder.address, fee_units * 10).build_transaction({
            "from": operator.address,
            "nonce": w3.eth.get_transaction_count(operator.address),
            "gas": 80_000,
            "gasPrice": w3.eth.gas_price,
            "chainId": settings.arc_chain_id,
        })
        signed = w3.eth.account.sign_transaction(approve, operator.key)
        w3.eth.wait_for_transaction_receipt(
            w3.eth.send_raw_transaction(signed.raw_transaction)
        )

    fill_tx = builder.functions.reportAttributedFill(builder_code_bytes, fee_units).build_transaction({
        "from": operator.address,
        "nonce": w3.eth.get_transaction_count(operator.address),
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
        "chainId": settings.arc_chain_id,
    })
    signed = w3.eth.account.sign_transaction(fill_tx, operator.key)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    rcpt = w3.eth.wait_for_transaction_receipt(h)

    return AttributedOrder(
        builder_code=builder_code,
        market_question=market_question,
        side=side,
        size_usdc=size_usdc,
        fill_price=0.5,
        builder_fee_usdc=fee_units / 1_000_000,
        tx_hash=rcpt.transactionHash.hex(),
        venue="mock-builder",
    )


# ----------------------------------------------------------------------------
# real path — Polymarket V2 CLOB
# ----------------------------------------------------------------------------

async def _place_real(
    *,
    builder_code: str,
    market_question: str,
    side: str,
    size_usdc: float,
) -> AttributedOrder:
    """Real-mode adapter. Lazily imports the CLOB client.

    Kept intentionally narrow — full order routing is out of scope for the
    hackathon prototype; this exists so the real-mode wire-up path is documented.
    """
    import httpx  # type: ignore

    # The V2 CLOB exposes a JSON HTTP API; we send a minimal limit order
    # with our builder code attached. For the hackathon submission we only
    # need the order to be accepted — fills are eventual.
    payload = {
        "market_question": market_question,
        "side": side,
        "size": size_usdc,
        "price": 0.5,
        "builder_code": builder_code,
    }
    headers = {
        "x-api-key": settings.poly_api_key or "",
        "x-api-secret": settings.poly_api_secret or "",
        "x-api-passphrase": settings.poly_api_passphrase or "",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            f"{settings.poly_clob_host}/order",
            json=payload,
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()

    return AttributedOrder(
        builder_code=builder_code,
        market_question=market_question,
        side=side,
        size_usdc=size_usdc,
        fill_price=data.get("price", 0.5),
        builder_fee_usdc=size_usdc * 0.01,
        tx_hash=data.get("tx_hash"),
        venue="polymarket-v2",
    )


def builder_fees_earned(builder_code: str) -> float:
    """Read the cumulative USDC builder fees credited to this agentId."""
    if not settings.polymarket_builder_address:
        return 0.0
    w3 = _w3()
    builder = w3.eth.contract(
        address=Web3.to_checksum_address(settings.polymarket_builder_address),
        abi=_load_abi("MockPolymarketBuilder"),
    )
    amount = builder.functions.builderFeesEarned(
        bytes.fromhex(builder_code.removeprefix("0x"))
    ).call()
    return amount / 1_000_000
