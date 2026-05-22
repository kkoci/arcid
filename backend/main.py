"""ArcID FastAPI surface.

Endpoints:
  GET  /health                      → liveness
  GET  /config                      → resolved addresses + mode flags
  POST /register                    → register an agent (returns canonical record)
  GET  /agents                      → leaderboard (paginated)
  GET  /agents/{agent_id}           → single agent
  POST /agents/{agent_id}/decide    → run the demo sentiment cycle for this agent
  POST /agents/{agent_id}/order     → place an attributed Polymarket order
  GET  /agents/{agent_id}/fees      → cumulative USDC builder fees
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .agent.tee_agent import SentimentDecision, run_decision_cycle
from .bridge.polymarket import builder_fees_earned, place_attributed_order
from .config import settings
from .registry.register import (
    RegistrationResult,
    get_agent,
    list_agents,
    register_agent,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("arcid.backend")

app = FastAPI(title="ArcID", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# request / response models
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    name: str = Field(..., max_length=64, examples=["Sentiment Sigma"])
    # Optional — caller can pre-generate the agent key inside the CVM.
    agent_private_key: Optional[str] = None


class RegisterResponse(BaseModel):
    agent_id: str
    attested_signer: str
    mrtd_hex: str
    wallet_address: str
    wallet_id: str
    tx_hash: str
    bind_tx_hash: Optional[str]
    gas_sponsored: bool
    name: str

    @classmethod
    def from_result(cls, r: RegistrationResult) -> "RegisterResponse":
        return cls(
            agent_id=r.agent_id,
            attested_signer=r.attested_signer,
            mrtd_hex=r.mrtd_hex,
            wallet_address=r.wallet.address,
            wallet_id=r.wallet.wallet_id,
            tx_hash=r.tx_hash,
            bind_tx_hash=r.bind_tx_hash,
            gas_sponsored=r.gas_sponsored,
            name=r.name,
        )


class DecideRequest(BaseModel):
    market_question: str
    signals: list[str] = Field(default_factory=list)


class OrderRequest(BaseModel):
    market_question: str
    side: str = Field(..., pattern="^(YES|NO)$")
    size_usdc: float = Field(..., gt=0, le=100.0)


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/config")
def get_config() -> dict:
    return {
        "arc_rpc_url": settings.arc_rpc_url,
        "arc_chain_id": settings.arc_chain_id,
        "addresses": {
            "USDC": settings.usdc_token_address,
            "DCAPVerifier": settings.dcap_verifier_address,
            "ArcIDRegistry": settings.arcid_registry_address,
            "PolymarketBuilder": settings.polymarket_builder_address,
        },
        "modes": {
            "prototype_mode": settings.prototype_mode,
            "real_phala": settings.use_real_phala,
            "real_circle": settings.use_real_circle,
            "real_polymarket": settings.use_real_polymarket,
        },
    }


@app.post("/register", response_model=RegisterResponse)
async def register(req: RegisterRequest) -> RegisterResponse:
    try:
        result = await register_agent(
            req.name,
            agent_private_key=req.agent_private_key,
        )
        return RegisterResponse.from_result(result)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/agents")
def get_agents(offset: int = 0, limit: int = 50) -> dict:
    try:
        agents = list_agents(offset=offset, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    # enrich with builder fees
    for a in agents:
        try:
            a["builder_fees_usdc"] = builder_fees_earned(a["agent_id"])
        except Exception:
            a["builder_fees_usdc"] = 0.0
    return {"agents": agents, "total": len(agents)}


@app.get("/agents/{agent_id}")
def get_one(agent_id: str) -> dict:
    try:
        a = get_agent(agent_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        a["builder_fees_usdc"] = builder_fees_earned(agent_id)
    except Exception:
        a["builder_fees_usdc"] = 0.0
    return a


@app.post("/agents/{agent_id}/decide", response_model=SentimentDecision)
def decide(agent_id: str, req: DecideRequest) -> SentimentDecision:
    return run_decision_cycle(req.market_question, req.signals)


@app.post("/agents/{agent_id}/order")
async def order(agent_id: str, req: OrderRequest) -> dict:
    try:
        agent = get_agent(agent_id)
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
    if int(agent["wallet"], 16) == 0:
        raise HTTPException(status_code=400, detail="agent wallet not bound yet")
    res = await place_attributed_order(
        builder_code=agent_id,
        fee_recipient=agent["wallet"],
        market_question=req.market_question,
        side=req.side,
        size_usdc=req.size_usdc,
    )
    return {
        "builder_code": res.builder_code,
        "market_question": res.market_question,
        "side": res.side,
        "size_usdc": res.size_usdc,
        "fill_price": res.fill_price,
        "builder_fee_usdc": res.builder_fee_usdc,
        "tx_hash": res.tx_hash,
        "venue": res.venue,
    }


@app.get("/agents/{agent_id}/fees")
def fees(agent_id: str) -> dict:
    return {"agent_id": agent_id, "builder_fees_usdc": builder_fees_earned(agent_id)}
