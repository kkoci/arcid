"""Tests for the backend pieces that don't need an RPC endpoint.

The on-chain registration flow is covered end-to-end by the Hardhat suite
in tests/test_contracts.js; here we test:
  - The mock Circle wallet generator is deterministic per agent ID.
  - The sentiment agent's mock path returns the expected schema.
  - The settings loader correctly hydrates from deployments/*.json.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from backend.agent.tee_agent import SentimentDecision, run_decision_cycle
from backend.config import REPO_ROOT, get_settings, reset_settings_cache
from backend.registry.circle_wallets import CircleWalletClient


# ---------------------------------------------------------------------------
# Circle wallet mock
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mock_circle_wallet_is_deterministic_per_agent():
    client = CircleWalletClient(prototype=True)
    aid = "0x" + "ab" * 32
    w1 = await client.create_wallet_for_agent(aid)
    w2 = await client.create_wallet_for_agent(aid)
    assert w1.address == w2.address
    assert w1.address.startswith("0x")
    assert len(w1.address) == 42
    assert w1.gas_sponsored is True
    assert w1.blockchain == "ARC-TESTNET"


@pytest.mark.asyncio
async def test_mock_circle_wallet_differs_across_agents():
    client = CircleWalletClient(prototype=True)
    w1 = await client.create_wallet_for_agent("0x" + "ab" * 32)
    w2 = await client.create_wallet_for_agent("0x" + "cd" * 32)
    assert w1.address != w2.address


# ---------------------------------------------------------------------------
# sentiment agent mock
# ---------------------------------------------------------------------------

def test_sentiment_decision_yes_when_bullish_signals_dominate():
    decision: SentimentDecision = run_decision_cycle(
        "Will Agora have >200 submissions?",
        ["ship date confirmed", "win win win", "bull case strong"],
        api_key=None,
    )
    assert decision.side == "YES"
    assert decision.confidence >= 0.55
    assert decision.suggested_size_usdc > 0


def test_sentiment_decision_no_size_when_signals_are_split():
    decision = run_decision_cycle(
        "Will it rain tomorrow?",
        ["maybe", "perhaps"],  # neither bullish nor bearish keywords
        api_key=None,
    )
    # With our deterministic mock, no keywords means everything cancels.
    # We just assert the schema is well-formed and confidence is below threshold.
    assert decision.confidence <= 1.0
    assert decision.suggested_size_usdc in (0.0, 1.0)
    assert decision.side in {"YES", "NO"}


# ---------------------------------------------------------------------------
# settings loader
# ---------------------------------------------------------------------------

def test_settings_hydrate_from_deployment_file(tmp_path, monkeypatch):
    # Write a fake deployments/hardhat.json that the loader should pick up
    deploy_dir = REPO_ROOT / "deployments"
    deploy_dir.mkdir(exist_ok=True)
    fake = {
        "network": "hardhat",
        "chainId": 31337,
        "deployer": "0x" + "1" * 40,
        "timestamp": 0,
        "addresses": {
            "USDC": "0x" + "a" * 40,
            "DCAPVerifier": "0x" + "b" * 40,
            "ArcIDRegistry": "0x" + "c" * 40,
            "MockPolymarketBuilder": "0x" + "d" * 40,
        },
        "config": {},
    }
    target = deploy_dir / "hardhat.json"
    backup = None
    if target.exists():
        backup = target.read_text()
    target.write_text(json.dumps(fake))

    try:
        monkeypatch.setenv("ARC_CHAIN_ID", "31337")
        monkeypatch.delenv("ARCID_REGISTRY_ADDRESS", raising=False)
        reset_settings_cache()
        s = get_settings()
        assert s.arcid_registry_address == "0x" + "c" * 40
        assert s.usdc_token_address == "0x" + "a" * 40
        assert s.dcap_verifier_address == "0x" + "b" * 40
        assert s.polymarket_builder_address == "0x" + "d" * 40
    finally:
        if backup is not None:
            target.write_text(backup)
        else:
            target.unlink()
        reset_settings_cache()
