"""Demo "Sentiment Agent".

Per the brief, this is the agent that proves the full loop end-to-end:
  1. Lives inside a Phala TDX CVM.
  2. Reads a sentiment signal (Discord / Twitter mock here).
  3. Places a Polymarket V2 attributed order using its ArcID as builder code.
  4. Receives USDC builder fees to its Circle Programmable Wallet.

Inside the CVM, the agent's private key never leaves the enclave. The
`attestation` module proves to ArcID that this code controls that key.

For the prototype we ship a single-shot `run_decision_cycle()` that returns
the synthesized decision; the registration handler invokes it on-demand.
The reasoning model is Claude Sonnet 4.6 — chosen because it's the most
recent fast-tier Claude (Opus is overkill for sentiment scoring) and the
brief calls out Sonnet specifically.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional

from ..config import settings

logger = logging.getLogger(__name__)


@dataclass
class SentimentDecision:
    market_question: str
    side: str          # "YES" | "NO"
    confidence: float  # 0.0–1.0
    rationale: str
    suggested_size_usdc: float


# A canned, hackathon-relevant prompt. In production this is parameterised by
# market and a sliding feed of signals. The decision schema is fixed so the
# bridge layer can route the order without re-parsing free text.
SYSTEM_PROMPT = """\
You are a sentiment-driven prediction-market agent.
You read short signal windows and emit a single trading decision.

Output strict JSON matching:
{
  "market_question": str,
  "side": "YES" | "NO",
  "confidence": float in [0,1],
  "rationale": str (<=200 chars),
  "suggested_size_usdc": float (<= 5.0 for the demo)
}

Be conservative — confidence below 0.55 means do not trade (size=0).
"""


def _mock_decision(market_question: str, signals: list[str]) -> SentimentDecision:
    """Deterministic stand-in when ANTHROPIC_API_KEY is absent."""
    positives = sum(
        1 for s in signals if any(w in s.lower() for w in ("up", "win", "yes", "bull", "ship"))
    )
    negatives = sum(
        1 for s in signals if any(w in s.lower() for w in ("down", "lose", "no", "bear", "delay"))
    )
    total = max(positives + negatives, 1)
    side = "YES" if positives >= negatives else "NO"
    confidence = max(positives, negatives) / total
    size = 1.0 if confidence >= 0.55 else 0.0
    return SentimentDecision(
        market_question=market_question,
        side=side,
        confidence=round(confidence, 2),
        rationale=f"mock: {positives} bullish vs {negatives} bearish signals",
        suggested_size_usdc=size,
    )


def run_decision_cycle(
    market_question: str,
    signals: list[str],
    *,
    api_key: Optional[str] = None,
) -> SentimentDecision:
    """Run one sentiment → decision cycle.

    Falls back to a deterministic mock when no Anthropic API key is configured.
    """
    api_key = api_key or settings.anthropic_api_key
    if not api_key:
        logger.info("No ANTHROPIC_API_KEY — using mock decision.")
        return _mock_decision(market_question, signals)

    # Imported lazily so prototype-mode users don't need the package installed.
    from anthropic import Anthropic  # type: ignore

    client = Anthropic(api_key=api_key)
    user_payload = json.dumps({"market": market_question, "signals": signals})

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_payload}],
    )
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("Sentiment agent returned non-JSON; falling back to mock.")
        return _mock_decision(market_question, signals)

    return SentimentDecision(
        market_question=data.get("market_question", market_question),
        side=data["side"],
        confidence=float(data["confidence"]),
        rationale=data.get("rationale", ""),
        suggested_size_usdc=float(data.get("suggested_size_usdc", 0.0)),
    )
