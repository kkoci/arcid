"""Central settings loader.

Loaded once at import time. Reads `.env` if present. Every external integration
has both real-mode credentials and a `PROTOTYPE_MODE` flag; absent credentials
flip that subsystem to its mock implementation automatically, so the developer
can run the full stack without provisioning anything.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Arc
    arc_rpc_url: str = Field(default="http://127.0.0.1:8545", alias="ARC_RPC_URL")
    arc_chain_id: int = Field(default=31337, alias="ARC_CHAIN_ID")
    deployer_private_key: str = Field(
        default="0x" + "0" * 63 + "1",
        alias="DEPLOYER_PRIVATE_KEY",
    )

    # Resolved at boot from deployments/<network>.json if not set directly.
    usdc_token_address: Optional[str] = Field(default=None, alias="USDC_TOKEN_ADDRESS")
    dcap_verifier_address: Optional[str] = Field(default=None, alias="DCAP_VERIFIER_ADDRESS")
    arcid_registry_address: Optional[str] = Field(default=None, alias="ARCID_REGISTRY_ADDRESS")
    polymarket_builder_address: Optional[str] = Field(default=None, alias="POLYMARKET_BUILDER_ADDRESS")

    # Circle
    circle_api_key: Optional[str] = Field(default=None, alias="CIRCLE_API_KEY")
    circle_wallet_set_id: Optional[str] = Field(default=None, alias="CIRCLE_WALLET_SET_ID")
    circle_entity_secret: Optional[str] = Field(default=None, alias="CIRCLE_ENTITY_SECRET")
    paymaster_url: Optional[str] = Field(default=None, alias="PAYMASTER_URL")

    # Anthropic (demo sentiment agent)
    anthropic_api_key: Optional[str] = Field(default=None, alias="ANTHROPIC_API_KEY")

    # Phala TDX
    phala_cloud_api_key: Optional[str] = Field(default=None, alias="PHALA_CLOUD_API_KEY")
    phala_cvm_endpoint: Optional[str] = Field(default=None, alias="PHALA_CVM_ENDPOINT")

    # Polymarket
    poly_clob_host: str = Field(default="https://clob.polymarket.com", alias="POLY_CLOB_HOST")
    poly_builder_code: Optional[str] = Field(default=None, alias="POLY_BUILDER_CODE")
    poly_api_key: Optional[str] = Field(default=None, alias="POLY_API_KEY")
    poly_api_secret: Optional[str] = Field(default=None, alias="POLY_API_SECRET")
    poly_api_passphrase: Optional[str] = Field(default=None, alias="POLY_API_PASSPHRASE")

    # Backend
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")
    prototype_mode: bool = Field(default=True, alias="PROTOTYPE_MODE")
    # Comma-separated list of allowed CORS origins, or "*" for open (prototype default).
    allowed_origins: str = Field(default="*", alias="ALLOWED_ORIGINS")
    # Circle blockchain identifier — "ARC-TESTNET" or "ARC".
    arc_network: str = Field(default="ARC-TESTNET", alias="ARC_NETWORK")

    # ---- derived ----

    def load_deployment(self, network: str = "hardhat") -> None:
        """Hydrate contract addresses from `deployments/<network>.json` when
        the developer has not set them in the env. Idempotent.

        An address is considered unset if it is None, empty, or the zero
        address — the .env.example ships zero-address placeholders that
        should defer to the deployment file."""
        path = REPO_ROOT / "deployments" / f"{network}.json"
        if not path.exists():
            return
        data = json.loads(path.read_text())
        addrs = data.get("addresses", {})

        zero = "0x" + "0" * 40

        def _pick(current: Optional[str], from_file: Optional[str]) -> Optional[str]:
            if current and current.lower() != zero:
                return current
            return from_file

        self.usdc_token_address = _pick(self.usdc_token_address, addrs.get("USDC"))
        self.dcap_verifier_address = _pick(self.dcap_verifier_address, addrs.get("DCAPVerifier"))
        self.arcid_registry_address = _pick(self.arcid_registry_address, addrs.get("ArcIDRegistry"))
        self.polymarket_builder_address = _pick(
            self.polymarket_builder_address, addrs.get("MockPolymarketBuilder")
        )

    @property
    def cors_origins(self) -> list[str]:
        if self.allowed_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def use_real_circle(self) -> bool:
        return bool(self.circle_api_key and self.circle_wallet_set_id and not self.prototype_mode)

    @property
    def use_real_phala(self) -> bool:
        return bool(self.phala_cloud_api_key and self.phala_cvm_endpoint and not self.prototype_mode)

    @property
    def use_real_polymarket(self) -> bool:
        return bool(
            self.poly_api_key and self.poly_api_secret and self.poly_api_passphrase
            and not self.prototype_mode
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    if s.arc_chain_id == 31337:
        s.load_deployment("localhost")  # persistent node (npm run node + deploy:dev)
        s.load_deployment("hardhat")    # ephemeral fallback (deploy:local)
    else:
        s.load_deployment("arcTestnet")
    return s


def reset_settings_cache() -> None:
    """Test helper — re-reads .env on next get_settings() call."""
    get_settings.cache_clear()


# Convenience export so other modules can import a module-level singleton.
settings = get_settings()
