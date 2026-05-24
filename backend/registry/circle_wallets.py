"""Circle Programmable Wallets integration.

Real mode hits the developer-controlled-wallets API
(https://developers.circle.com/w3s/docs/programmable-wallets-overview).
Each registered ArcID agent gets its own SCA wallet on Arc whose owner is
Circle's MPC; the agent invokes the wallet via Circle's signing endpoint.

Prototype mode uses an in-memory generator. Deterministic per `agent_id`,
so re-running the backend reproduces the same address — useful for screenshots
and tests.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Optional

from eth_account import Account
from eth_utils import keccak

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class CircleWallet:
    wallet_id: str
    address: str
    blockchain: str           # "ARC-TESTNET" | "ARC"
    custody_type: str         # "SCA"
    state: str                # "LIVE"
    gas_sponsored: bool


class CircleWalletClient:
    """Thin adapter — `create_wallet_for_agent()` is the only entry point the
    registration flow uses."""

    def __init__(self, prototype: Optional[bool] = None):
        self.prototype = settings.prototype_mode if prototype is None else prototype
        self._cache: dict[str, CircleWallet] = {}

    async def create_wallet_for_agent(self, agent_id_hex: str) -> CircleWallet:
        if agent_id_hex in self._cache:
            return self._cache[agent_id_hex]

        if self.prototype or not settings.use_real_circle:
            wallet = self._create_mock(agent_id_hex)
        else:
            try:
                wallet = await self._create_real(agent_id_hex)
            except Exception as exc:
                logger.warning("Circle API failed (%s) — falling back to mock wallet.", exc)
                wallet = self._create_mock(agent_id_hex)
        self._cache[agent_id_hex] = wallet
        return wallet

    # ---- mock ----

    def _create_mock(self, agent_id_hex: str) -> CircleWallet:
        # Deterministic address: keccak(agentId) → take last 20 bytes
        seed = bytes.fromhex(agent_id_hex.removeprefix("0x"))
        priv = keccak(b"arcid-mock-wallet" + seed)
        addr = Account.from_key(priv).address
        wallet_id = f"mock-{seed[:6].hex()}"
        logger.debug("Mock Circle wallet %s for agent %s", addr, agent_id_hex)
        return CircleWallet(
            wallet_id=wallet_id,
            address=addr,
            blockchain=settings.arc_network,
            custody_type="SCA",
            state="LIVE",
            gas_sponsored=True,
        )

    # ---- real ----

    async def _create_real(self, agent_id_hex: str) -> CircleWallet:
        from circle.web3 import developer_controlled_wallets, utils  # type: ignore

        client = utils.init_developer_controlled_wallets_client(
            api_key=settings.circle_api_key,
            entity_secret=settings.circle_entity_secret,
        )
        wallets_api = developer_controlled_wallets.WalletsApi(client)

        idempotency_key = str(uuid.uuid5(uuid.NAMESPACE_URL, f"arcid:{agent_id_hex}"))
        req = developer_controlled_wallets.CreateWalletRequest.from_dict({
            "idempotencyKey": idempotency_key,
            "walletSetId": settings.circle_wallet_set_id,
            "blockchains": [settings.arc_network],
            "accountType": "EOA",
            "count": 1,
        })
        resp = wallets_api.create_wallet(req)
        import json as _json
        data = _json.loads(resp.model_dump_json())
        wallet = data["data"]["wallets"][0]

        return CircleWallet(
            wallet_id=wallet["id"],
            address=wallet["address"],
            blockchain=wallet["blockchain"],
            custody_type=wallet.get("account_type", wallet.get("accountType", "EOA")),
            state=wallet.get("state", "LIVE"),
            gas_sponsored=True,
        )


# module-level singleton — cheap to construct, no I/O at import time
circle_wallets = CircleWalletClient()


async def create_wallet_for_agent(agent_id_hex: str) -> CircleWallet:
    return await circle_wallets.create_wallet_for_agent(agent_id_hex)


# Convenience for synchronous test contexts.
def create_wallet_sync(agent_id_hex: str) -> CircleWallet:
    return asyncio.run(create_wallet_for_agent(agent_id_hex))
