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
├── cli/
│   ├── arcid_cli.py               CLI tool — wraps the backend REST API
│   └── pyproject.toml             pip installable as arcid-cli
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
├── docker-compose.yml             Run backend from Docker Hub image (no Phala)
├── hardhat.config.js
├── package.json
├── .env.example                   All env vars with prototype defaults and prod comments
├── RUN.md                         Step-by-step run guide (local + production + CLI)
├── CLI_CODE_GUIDE.md              CLI code walkthrough — what, how, when, where
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

The Swagger UI is at **http://localhost:8000/docs**.

---

## CLI

A thin command-line wrapper around the backend API. Install once, use from any terminal.

```powershell
pip install -e cli\
```

```powershell
arcid health
arcid config
arcid register --name "My Agent"
arcid agents list
arcid agents inspect 0x532624        # prefix is enough
arcid agents fees 0x532624
arcid agents decide 0x532624 --market "Will X happen?" --signal "bull signal" --signal "another signal"
arcid agents order 0x532624 --market "Will X happen?" --side YES --size 1
```

Point at any backend with `--endpoint`:

```powershell
arcid --endpoint https://arcid-xsjx.onrender.com agents list
```

Use `--json` before any sub-command for raw JSON output (useful for scripting):

```powershell
$id = (arcid --json register --name "Bot" | ConvertFrom-Json).agent_id
```

See [`CLI_CODE_GUIDE.md`](./CLI_CODE_GUIDE.md) for the full code walkthrough.

---

## Prototype vs real mode

Each external dependency has two implementations behind the same Python interface. The switch is `PROTOTYPE_MODE=true/false` plus the presence of credentials — no `if mock` scattered through business logic.

| Adapter | Real mode trigger | Prototype behaviour |
|---------|------------------|---------------------|
| `generate_attestation()` | `PHALA_CLOUD_API_KEY` + `PHALA_CVM_ENDPOINT` set, `PROTOTYPE_MODE=false` | Builds a structurally valid TDX v4 quote in Python; same byte layout the verifier expects |
| `create_wallet_for_agent()` | `CIRCLE_API_KEY` + `CIRCLE_WALLET_SET_ID` set, `PROTOTYPE_MODE=false` | `keccak("arcid-mock-wallet" ‖ agentId)` → deterministic address |
| `place_attributed_order()` | Polymarket credentials set, `PROTOTYPE_MODE=false` | Drives `MockPolymarketBuilder` on the Hardhat node — real ERC20 transfer, real on-chain fee accumulation |
| `run_decision_cycle()` | `ANTHROPIC_API_KEY` set | Keyword-counting sentiment fallback |

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

---

## Smart contracts

### `ArcIDRegistry.sol`

The canonical registry. Key design calls:

- **`agentId = keccak256(abi.encode(mrtd, reportData, attestedSigner))`** — three-field hash ties the ID to code + hardware + key simultaneously
- **Idempotency** — re-submitting a known attestation returns the existing ID without charging again
- **Sponsored quota** — on-chain counter tracks gas-sponsored registrations
- **`bindWallet` is owner-only** — only the registry operator can bind a Circle wallet to an agent ID
- **Custom errors** — `InvalidAttestation`, `InsufficientFee`, `WalletAlreadyBound`, `UnknownAgent`
- **`listAgents(offset, limit)`** — paginated struct array for cheap leaderboard reads

### `DCAPVerifier.sol`

Lightweight structural verifier. Validates the TDX v4 header, checks quote length and mrtd non-zero, and recovers the agent's signer via `ecrecover`. Cost: ~5K gas. The full Automata verifier (~2M gas) is the Day 2 port.

### `MockPolymarketBuilder.sol`

Implements `IPolymarketBuilder`. On each attributed fill it pulls USDC from the caller and forwards it to the agent's registered wallet — makes the prototype leaderboard show real non-zero fees.

---

## Configuration reference

All settings live in `.env` (copy from `.env.example`).

| Variable | Default | Production value |
|----------|---------|-----------------|
| `PROTOTYPE_MODE` | `true` | `false` |
| `ARC_RPC_URL` | `http://127.0.0.1:8545` | `https://rpc.testnet.arc.network` |
| `ARC_CHAIN_ID` | `31337` | `5042002` |
| `ARC_NETWORK` | `ARC-TESTNET` | `ARC-TESTNET` |
| `DEPLOYER_PRIVATE_KEY` | Hardhat default key | Dedicated funded wallet key |
| `USDC_TOKEN_ADDRESS` | Auto from deploy | `0x3600000000000000000000000000000000000000` |
| `ARCID_REGISTRY_ADDRESS` | Auto from deploy | From `deployments/arcTestnet.json` |
| `CIRCLE_API_KEY` | _(empty → mock)_ | Circle developer key |
| `CIRCLE_WALLET_SET_ID` | _(empty → mock)_ | Circle wallet set ID |
| `CIRCLE_ENTITY_SECRET` | _(empty → mock)_ | Circle entity secret (32-byte hex) |
| `ANTHROPIC_API_KEY` | _(empty → keyword fallback)_ | Anthropic key — optional, only needed for real sentiment decisions |
| `PHALA_CLOUD_API_KEY` | _(empty → mock attestation)_ | Phala Cloud key — optional, see Phala section below |
| `PHALA_CVM_ENDPOINT` | _(empty → mock attestation)_ | `http://127.0.0.1:9000` inside CVM |
| `POLY_API_KEY` / `SECRET` / `PASSPHRASE` | _(empty → mock builder)_ | Polymarket V2 CLOB credentials — see note below |
| `ALLOWED_ORIGINS` | `*` | `https://your-frontend.vercel.app` |
| `VITE_API_BASE_URL` | _(empty → `/api` via Vite proxy)_ | `https://arcid-xsjx.onrender.com` |

---

## Phala TDX deployment (optional — real hardware attestation)

Phala Cloud runs the backend inside a genuine Intel TDX enclave, making the DCAP attestation hardware-rooted rather than synthetic. The backend automatically detects Phala credentials and switches from mock to real attestation — no code changes needed.

### Step 1 — build and push the Docker image

```powershell
docker build -t YOUR_DOCKERHUB_USER/arcid-agent:0.1.0 -f phala/Dockerfile .
docker push YOUR_DOCKERHUB_USER/arcid-agent:0.1.0
```

### Step 2 — deploy on Phala Cloud

Go to `cloud.phala.network`, create a new CVM, paste `docker-compose.yml` in the editor (update the image name to match your Docker Hub), then fill in the two sections below.

**Encrypted Secrets** (paste in Phala's Secrets section — encrypted inside TDX, never logged):

```
DEPLOYER_PRIVATE_KEY=0x...
CIRCLE_API_KEY=...
CIRCLE_ENTITY_SECRET=...
CIRCLE_WALLET_SET_ID=...
ANTHROPIC_API_KEY=...
```

**Environment variables** (plain env section — already set in `docker-compose.yml` but override here if needed):

```
PROTOTYPE_MODE=false
ARC_RPC_URL=https://rpc.testnet.arc.network
ARC_CHAIN_ID=5042002
ARC_NETWORK=ARC-TESTNET
USDC_TOKEN_ADDRESS=0x3600000000000000000000000000000000000000
ARCID_REGISTRY_ADDRESS=0xa3705BFBDD53e2DB059698EE0Ac7093a70d81b9E
DCAP_VERIFIER_ADDRESS=0xBB2835fC4d189340a98084A50DD0B36b4Ff50Ca2
PAYMASTER_URL=https://paymaster.circle.com/v1/arc-testnet
```

### Step 3 — test

```powershell
arcid --endpoint https://<your-cvm-url> health
arcid --endpoint https://<your-cvm-url> register --name "Phala Test"
```

---

## Deploying to Render + Vercel (production without Phala)

The public deployment runs the backend on Render (synthetic attestation, all other integrations real) and the frontend on Vercel.

### Backend — Render

1. Go to `render.com` → **New** → **Web Service**
2. Connect your GitHub repo (`kkoci/arcid`)
3. Set **Dockerfile Path** to `phala/Dockerfile`
4. Add all environment variables in Render's env vars section (see Configuration reference above)
5. Deploy — Render builds from the Dockerfile and serves on a public URL

Live backend: `https://arcid-xsjx.onrender.com`

### Frontend — Vercel

1. Go to `vercel.com` → **New Project** → import `kkoci/arcid` from GitHub
2. Select **frontend** as the root directory
3. Add environment variable: `VITE_API_BASE_URL=https://arcid-xsjx.onrender.com`
4. Deploy

Live frontend: `https://arcid-jade.vercel.app`

---

## Polymarket attribution (nice to have)

The Polymarket V2 CLOB attribution bridge is implemented (`backend/bridge/polymarket.py`) and the agent ID works as a builder code out of the box. Set `POLY_API_KEY`, `POLY_API_SECRET`, and `POLY_API_PASSPHRASE` from your Polymarket account to enable live attributed orders.

**Note:** Polymarket trading is currently geo-restricted in many regions including the US, UK, and most of the EU. If you are in a blocked region, the backend falls back to synthetic orders automatically — the attribution architecture is unchanged, just the venue is simulated.

---

## Live deployment notes

The public backend runs on Render (`https://arcid-xsjx.onrender.com`). Render's free tier auto-suspends idle instances after 15 minutes of inactivity and wakes them on the first incoming request. The first request after an idle period takes ~30 seconds while the instance boots — subsequent requests are fast.

The frontend leaderboard polls `/agents` every 8 seconds, which is enough to wake the backend automatically. If you open the frontend and the leaderboard takes a few seconds to load, that is normal — just wait and it will come back on its own.

---

## Known limitations (prototype)

1. **Simplified DCAP verifier is not Sybil-resistant.** Anyone can craft a structurally valid quote that passes. The full Automata verifier closes this.
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
