# ArcID — The Verifiable Agent Layer for Arc

> Agora Agents Hackathon · Canteen × Circle Arc · May 11–25, 2026
> Solo build by Kristian Koci

**ArcID** is a universal identity registry for AI agents, deployed on Circle's Arc blockchain. Any AI agent running inside an Intel TDX Trusted Execution Environment can register with ArcID by submitting a hardware-signed DCAP attestation receipt. In return it receives a canonical `bytes32` agent ID anchored permanently on Arc — a hardware-backed passport it can use to trade, be trusted, and get paid.

> *"Arc is the Economic OS for agents. But an economy without identity is just chaos. ArcID provides the hardware-backed passport that agents need to trade, be trusted, and get paid."*

---

## The problem

AI agents are becoming autonomous economic actors — placing bets on prediction markets, executing trades, earning fees. The infrastructure is ready for them (Arc, USDC, Polymarket V2). One piece is missing: **identity**.

When an agent operates across venues it has no single persistent identity:
- On **Polymarket V2** it needs a `bytes32` builder code
- On **Hyperliquid** it needs HIP-3 attribution
- On **Pump.fun** it needs a fee-recipient field

Three venues, three systems, no bridge. Worse — there is no way to *prove* an order came from a specific AI agent running specific code, rather than a human pretending to be an agent.

This creates three compounding problems:

| Problem | Description |
|---------|-------------|
| **Attribution** | Platforms pay fees to agents who bring them trades, but cannot verify who the agent actually is |
| **Copy-trading** | Users want to follow successful agents, but track records can be faked |
| **Pretender** | Humans mimic agents to farm agent-only incentives; no way to distinguish them |

In May 2026 the hackathon organisers (Canteen) published a research article explicitly identifying this as the unsolved gap:

> *"A registry contract on a settlement-grade chain that issues bytes32 agent codes and signs receipts that other venues can adopt would close this. Whoever ships that registry first defines the standard."*

ArcID is the answer to their own open question.

---

## The solution

### What is a TEE?

A Trusted Execution Environment (TEE) is a secure pocket inside a processor where code runs in complete isolation — not even the server owner can observe it. When code runs inside a TEE, the hardware produces a **DCAP attestation quote**: a cryptographic receipt signed by Intel that proves exactly which code is running, that it is running inside a genuine secure enclave, and that nobody has tampered with it.

This receipt cannot be faked. It is hardware-rooted identity.

### How ArcID works

```
┌─────────────────────────────────────────────────────────┐
│                     AI AGENT                            │
│         (running inside Intel TDX enclave               │
│              on Phala Cloud CVM)                        │
└──────────────────────┬──────────────────────────────────┘
                       │
                       │  1. Generate DCAP attestation quote
                       │     (hardware-signed by Intel)
                       ▼
┌─────────────────────────────────────────────────────────┐
│              ArcID REGISTRY  (Arc L1)                   │
│                                                         │
│  2. Verify DCAP quote on-chain                          │
│  3. Issue canonical  bytes32  agentId                   │
│  4. Create Circle Programmable Wallet for agent         │
│  5. Charge $0.10 USDC registration fee                  │
│  6. Emit  AgentRegistered  event                        │
└──────────────────────┬──────────────────────────────────┘
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
┌──────────────────┐    ┌──────────────────────┐
│  Polymarket V2   │    │    Hyperliquid        │
│  builder code    │    │    HIP-3 attribution  │
│  (bytes32 ID)    │    │    (stretch goal)     │
└──────────────────┘    └──────────────────────┘
```

The agent ID is derived as:

```
agentId = keccak256(abi.encode(mrtd, reportData, attestedSigner))
```

- `mrtd` — the 48-byte hardware measurement of the enclave code (from the TDX quote)
- `reportData` — a per-registration commitment: `keccak256(signerAddress ‖ nonce)`
- `attestedSigner` — the Ethereum address recovered from the agent's signature over `reportData`

All three fields pinned together means the ID describes *this code, on this hardware, with this key* — it cannot be replayed or spoofed.

---

## System architecture

```
┌───────────────────── Frontend (Vite / React / Tailwind) ──────────────────────┐
│  RegisterAgent ─┐                                                             │
│  Leaderboard  ──┼──► useArcID hook ──► /api/* (proxied to FastAPI on :8000)   │
│  OrderDialog  ──┘                                                             │
└───────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌───────────────────── Backend (FastAPI on Phala TDX CVM) ──────────────────────┐
│  POST /register ──► register_agent()                                          │
│     1. attestation.generate_attestation()   ← real TDX in prod                │
│     2. web3 → ArcIDRegistry.register()      ← Arc L1                          │
│     3. event decode → agentId                                                 │
│     4. circle_wallets.create_wallet_for_agent()  ← Circle API in prod         │
│     5. web3 → ArcIDRegistry.bindWallet()    ← Arc L1                          │
│                                                                               │
│  POST /agents/{id}/order ──► polymarket.place_attributed_order()              │
│     prototype: MockPolymarketBuilder on Arc                                   │
│     real:      Polymarket V2 CLOB HTTP                                        │
└───────────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────── Arc L1 (EVM) ───────────────────────────────────────┐
│  DCAPVerifier ───► ArcIDRegistry ───► MockPolymarketBuilder                   │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| TEE | Intel TDX via Phala Cloud CVM |
| Attestation | DCAP (structural verifier on-chain; full Automata port is Day 2) |
| Smart contracts | Solidity 0.8.24 → Arc (EVM-compatible) |
| Backend | FastAPI (Python 3.11+) + Web3.py |
| AI agent | Claude Sonnet 4.6 via Anthropic API |
| Frontend | React + Tailwind CSS (Vite) |
| Chain | Arc Testnet → Arc Mainnet |
| Identity primitive | `bytes32` agentId |
| Wallets | Circle Programmable Wallets (SCA, MPC-secured) |
| Gas | Circle Paymaster — USDC-denominated, first 100 registrations sponsored |
| Settlement | USDC native on Arc |
| Attribution bridge | Polymarket V2 builder codes |

---

## Circle developer tools

| Tool | How it's used |
|------|--------------|
| **Contracts** | Registry, DCAP verifier, fee logic — core of ArcID |
| **Programmable Wallets** | Each registered agent gets its own SCA wallet; Circle MPC secures the key |
| **Paymaster (Gas Station)** | First 100 registrations gas-sponsored; quota tracked on-chain |
| **USDC** | $0.10 registration fee; builder fees flow back to agent wallets |
| **App Kit** | Fee display and wallet interaction components in the UI |

---

## Repository layout

```
arcid/
├── contracts/
│   ├── ArcIDRegistry.sol          Main registry: register, getAgent, fee logic, leaderboard
│   ├── DCAPVerifier.sol           Structural DCAP v4 verifier + ecrecover signer recovery
│   ├── interfaces/
│   │   └── IPolymarketBuilder.sol Builder-code bridge interface
│   └── mocks/
│       ├── MockPolymarketBuilder.sol  Local attribution simulator (real ERC20 transfers)
│       └── MockUSDC.sol               6-decimal mintable USDC for local dev
├── backend/
│   ├── main.py                    FastAPI: 8 endpoints
│   ├── config.py                  Pydantic Settings, prototype/real mode flags
│   ├── agent/
│   │   ├── attestation.py         DCAP quote: mock locally, real via Phala TDX
│   │   └── tee_agent.py           Sentiment Sigma demo agent (Claude Sonnet 4.6)
│   ├── registry/
│   │   ├── register.py            Orchestrator: attest → on-chain → wallet → bind
│   │   └── circle_wallets.py      Circle Programmable Wallets adapter
│   └── bridge/
│       └── polymarket.py          Polymarket V2 CLOB adapter
├── frontend/
│   └── src/
│       ├── App.jsx                Layout, header (chain ID, prototype badge), footer
│       ├── hooks/useArcID.js      Single hook: API calls + 8s leaderboard polling
│       └── components/
│           ├── RegisterAgent.jsx  Name input → registration → confirmation card
│           ├── Leaderboard.jsx    Sorted agent list, error state
│           ├── AgentCard.jsx      TEE Verified badge, USDC fees, wallet address
│           └── OrderDialog.jsx    Market/side/size modal
├── phala/
│   ├── cvm_config.json            Phala Cloud CVM manifest (TDX, ports, secrets scoping)
│   └── Dockerfile                 python:3.11-slim image for Phala deployment
├── tests/
│   ├── test_contracts.js          Hardhat: 11 tests (verifier, registry, Polymarket loop)
│   ├── test_attestation.py        Python: attestation layout, signature recovery
│   ├── test_registry.py           Python: wallets, settings, sentiment schema
│   └── conftest.py                Forces PROTOTYPE_MODE=true, adds repo root to path
├── scripts/
│   └── deploy_arc.js              Hardhat deploy → writes deployments/<network>.json
├── hardhat.config.js
├── package.json
├── .env.example                   All env vars with prototype defaults and prod comments
├── RUN.md                         Step-by-step run guide (local + production)
├── PRODUCTION.md                  Production deployment checklist
└── BUILD_EXPLANATION.md           Full design rationale, decisions table, known cracks
```

---

## Quick start — prototype mode (no real keys needed)

Everything runs locally on a Hardhat node. No Arc testnet wallet, no Circle account, no Phala CVM required.

**Windows (PowerShell) — open four terminals in the repo root:**

```powershell
# One-time setup
npm install
Push-Location frontend; npm install; Pop-Location
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
Copy-Item .env.example .env
npm run compile
npm run test:contracts   # 11 tests should pass
pytest                   # 12 tests should pass
```

```powershell
# Window A — local Arc-like node
npm run node

# Window B — deploy contracts (run once, re-run if you restart A)
npm run deploy:dev

# Window C — backend
.\.venv\Scripts\Activate.ps1
npm run backend:dev

# Window D — frontend
npm run frontend:dev
```

Visit **http://localhost:5173**. Register an agent, watch the TEE Verified card appear. Click **Place demo order** and watch the USDC fee tick up on the leaderboard.

The Swagger UI is at **http://localhost:8000/docs**. On `POST /register`, leave `agent_private_key` blank — the backend generates a fresh key automatically.

---

## Prototype vs real mode

Each external dependency has two implementations behind the same Python interface. The switch is `PROTOTYPE_MODE=true/false` plus the presence of credentials — no `if mock` scattered through business logic.

| Adapter | Real mode trigger | Prototype behaviour |
|---------|------------------|---------------------|
| `generate_attestation()` | `PHALA_CLOUD_API_KEY` + `PHALA_CVM_ENDPOINT` set, `PROTOTYPE_MODE=false` | Builds a structurally valid TDX v4 quote in Python; same byte layout the verifier expects |
| `create_wallet_for_agent()` | `CIRCLE_API_KEY` + `CIRCLE_WALLET_SET_ID` set, `PROTOTYPE_MODE=false` | `keccak("arcid-mock-wallet" ‖ agentId)` → deterministic address |
| `place_attributed_order()` | Polymarket credentials set, `PROTOTYPE_MODE=false` | Drives `MockPolymarketBuilder` on the Hardhat node — real ERC20 transfer, real on-chain fee accumulation |
| `run_decision_cycle()` | `ANTHROPIC_API_KEY` set | Keyword-counting sentiment fallback |

The biggest win: the mock Polymarket builder pays USDC fees via a real ERC20 transfer on the local chain, so the leaderboard's "fees earned" counter is a real balance, not a fabricated number.

---

## API reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness check |
| `GET` | `/config` | Resolved addresses + mode flags (`real_phala`, `real_circle`, `real_polymarket`) |
| `POST` | `/register` | Full registration: attest → on-chain → wallet → bind. Body: `{ name, agent_private_key? }` |
| `GET` | `/agents?offset=&limit=` | Paginated leaderboard enriched with `builder_fees_usdc` |
| `GET` | `/agents/{id}` | Single agent record + fees |
| `POST` | `/agents/{id}/decide` | Run sentiment cycle for this agent. Body: `{ market_question, signals[] }` |
| `POST` | `/agents/{id}/order` | Place attributed Polymarket order. Body: `{ market_question, side: YES|NO, size_usdc }` |
| `GET` | `/agents/{id}/fees` | Cumulative USDC builder fees |

The `/config` endpoint is the fastest way to verify a deployment — confirm `prototype_mode: false` and all three `real_*` flags are `true` before going live.

---

## Smart contracts

### `ArcIDRegistry.sol`

The canonical registry. Key design calls:

- **`agentId = keccak256(abi.encode(mrtd, reportData, attestedSigner))`** — three-field hash ties the ID to code + hardware + key simultaneously
- **Idempotency** — re-submitting a known attestation returns the existing ID without charging again; autonomous agents that crash and restart don't drain USDC
- **Sponsored quota** — an on-chain counter tracks gas-sponsored registrations so the leaderboard badge is verifiable, not just a claim
- **`bindWallet` is owner-only** — only the registry operator (the backend) can bind a Circle wallet to an agent ID; the agent itself cannot claim a wallet it doesn't hold
- **Custom errors** — `InvalidAttestation`, `InsufficientFee`, `WalletAlreadyBound`, `UnknownAgent` — saves gas on revert paths vs `require` strings
- **`listAgents(offset, limit)`** — paginated struct array for cheap leaderboard reads

### `DCAPVerifier.sol`

Lightweight structural verifier. Validates the TDX v4 header (version, key type, TEE type), checks quote length and mrtd non-zero, and recovers the agent's signer via `ecrecover(reportData, v, r, s)`. Cost: ~5K gas. The full Automata verifier (~2M gas) is the Day 2 port; same external interface, drop-in replacement.

### `MockPolymarketBuilder.sol`

Implements `IPolymarketBuilder`. Accepts `registerBuilder(bytes32, address)` and `reportAttributedFill(bytes32, uint256)`. On each fill it pulls USDC from the caller and forwards it to the agent's registered wallet. This is what makes the prototype leaderboard show real non-zero fees without real Polymarket liquidity.

---

## Configuration reference

All settings live in `.env` (copy from `.env.example`). The backend reads them via Pydantic Settings at startup.

| Variable | Default | Production value |
|----------|---------|-----------------|
| `PROTOTYPE_MODE` | `true` | `false` |
| `ARC_RPC_URL` | `http://127.0.0.1:8545` | `https://rpc.testnet.arc.network` |
| `ARC_CHAIN_ID` | `31337` | `421614` (testnet) |
| `ARC_NETWORK` | `ARC-TESTNET` | `ARC-TESTNET` or `ARC` |
| `DEPLOYER_PRIVATE_KEY` | Hardhat default key | Dedicated funded key (secrets manager) |
| `USDC_TOKEN_ADDRESS` | Auto from deploy | Real USDC address on Arc |
| `CIRCLE_API_KEY` | _(empty → mock)_ | Circle developer key |
| `CIRCLE_WALLET_SET_ID` | _(empty → mock)_ | Circle wallet set ID |
| `CIRCLE_ENTITY_SECRET` | _(empty → mock)_ | Circle entity secret |
| `ANTHROPIC_API_KEY` | _(empty → keyword fallback)_ | Your Anthropic key |
| `PHALA_CLOUD_API_KEY` | _(empty → mock attestation)_ | Phala Cloud key |
| `PHALA_CVM_ENDPOINT` | _(empty → mock attestation)_ | `http://127.0.0.1:9000` inside CVM |
| `POLY_API_KEY` / `SECRET` / `PASSPHRASE` | _(empty → mock builder)_ | Polymarket V2 CLOB credentials |
| `ALLOWED_ORIGINS` | `*` | `https://arcid.xyz,https://www.arcid.xyz` |
| `VITE_API_BASE_URL` | _(empty → `/api` via Vite proxy)_ | `https://api.arcid.xyz` |

---

## Going to production

Full procedure in [`PRODUCTION.md`](./PRODUCTION.md). The short version:

```bash
# 1. Fill .env with real credentials, set PROTOTYPE_MODE=false
# 2. Deploy contracts to Arc testnet
npm run deploy:arc                # → writes deployments/arcTestnet.json

# 3. Build frontend
VITE_API_BASE_URL=https://api.arcid.xyz npm run frontend:build
# Deploy frontend/dist/ to Vercel / Cloudflare Pages / S3

# 4. Start production backend (behind nginx for TLS)
npm run backend:prod              # uvicorn --workers 2, no --reload
```

Verify at `/config` that all `real_*` flags are `true` before announcing.

---

## Known limitations (prototype)

1. **Simplified DCAP verifier is not Sybil-resistant.** Anyone can craft a structurally valid quote that passes. The full Automata verifier (requires Intel PCK cert chain) closes this and is the Day 2 task.
2. **Single deployer key** acts as registry owner, wallet binder, and Polymarket router. Production should compartmentalise these into separate roles.
3. **No rate-limiting on `POST /register`.** The $0.10 fee alone doesn't prevent spam if the sponsored quota is non-zero.
4. **Mock Circle wallet private key is derivable** from the `agentId`. Do not use the mock wallet client with real value.
5. **CORS is `*` by default.** Set `ALLOWED_ORIGINS` to your domain in production.

---

## Hackathon judging criteria

| Criterion | Weight | Position |
|-----------|--------|----------|
| **Agentic Sophistication** | 30% | Agent runs fully autonomously inside Intel TDX. Every decision is cryptographically verifiable by hardware. |
| **Traction** | 30% | Other hackathon participants register their agents on ArcID. $0.10 fee = real on-chain transaction volume. Target: 20+ agents by submission. |
| **Circle tool usage** | 20% | Contracts + Programmable Wallets + Paymaster + USDC + App Kit. |
| **Innovation** | 20% | Canteen's own May 2026 research identified this as unsolved. ArcID is the direct answer. First TEE-rooted cross-venue agent identity system. |

---

## License

MIT
