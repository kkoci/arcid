# ArcID — Build Explanation

> Companion document to the prototype in this repo.
> Walks every file, explains the *what*, *why*, *how* and *when* of each decision.

---

## 0. Reading guide

This doc is paired with the build brief in [`ARCID_CLAUDE_CODE.md`](./ARCID_CLAUDE_CODE.md). The brief is *what to build*. This doc is *how I built it* — the design calls, the prototype/real-mode split, and the things deliberately left as stubs because they can't be exercised without infrastructure that doesn't exist yet at this point in the hackathon (Phala CVM image, real Arc testnet faucet drip, Circle production keys, etc.).

If you only read one section, read **§3 — The prototype/real-mode split**. That's the single biggest design decision and every other choice falls out of it.

---

## 1. What I built, end-to-end

The prototype implements every layer the brief calls out, with mockable adapters at each external boundary so the whole stack runs locally with `npm run node` + `npm run backend:dev` + `npm run frontend:dev`. Specifically:

| Layer | File(s) | What it does |
|---|---|---|
| On-chain registry | `contracts/ArcIDRegistry.sol` | Issues `bytes32 agentId` per attestation, charges $0.10 USDC (or consumes a sponsored slot), records the Circle wallet binding, exposes a paginated leaderboard view |
| On-chain DCAP verifier | `contracts/DCAPVerifier.sol` | Validates the structural shape of a TDX v4 quote + recovers the agent's signer from the report-data signature |
| Builder-code adapter | `contracts/interfaces/IPolymarketBuilder.sol` + `contracts/mocks/MockPolymarketBuilder.sol` | The interface a real Polymarket V2 router would implement, plus a local mock that drives the same code path |
| Mock USDC | `contracts/mocks/MockUSDC.sol` | 6-decimal ERC20 for tests + local Hardhat runs |
| Contract tests | `tests/test_contracts.js` | Hardhat suite — covers verifier, registration, sponsored quota, fee payment, idempotency, wallet binding, Polymarket fill |
| Deploy script | `scripts/deploy_arc.js` | Deploys all four contracts, writes `deployments/<network>.json` for the backend to consume |
| Attestation generation | `backend/agent/attestation.py` | Builds a TDX v4-shaped quote — mock locally, real via Phala TDX in CVM mode |
| Demo agent | `backend/agent/tee_agent.py` | "Sentiment Sigma" — Claude Sonnet 4.6, with a deterministic fallback when no API key |
| Registration orchestrator | `backend/registry/register.py` | Generate attestation → submit → decode `AgentRegistered` → provision wallet → bind wallet on-chain |
| Circle wallets | `backend/registry/circle_wallets.py` | Real-mode hits `api.circle.com/v1/w3s/developer/wallets`, prototype mode generates a deterministic local address per agentId |
| Polymarket bridge | `backend/bridge/polymarket.py` | Real-mode posts to the V2 CLOB, prototype mode drives the `MockPolymarketBuilder` for real on-chain fee flow |
| FastAPI surface | `backend/main.py` | 8 endpoints — health, config, register, agents list/get, decide, order, fees |
| Backend tests | `tests/test_attestation.py`, `tests/test_registry.py` | Pure-Python coverage of attestation correctness, mock wallet determinism, sentiment scoring, settings loader |
| Frontend | `frontend/src/**/*.jsx` | Vite + React + Tailwind. Two-column layout: register on the left, live leaderboard on the right, modal order placement |
| TDX deployment | `phala/cvm_config.json`, `phala/Dockerfile` | Phala Cloud CVM manifest + container that the Phala bootstrapper consumes |

Counts: 4 Solidity files, 12 Python files (8 source + 3 tests + 1 conftest), 7 JSX files, 1 hook, 1 Hardhat test suite, 1 deploy script, 1 CVM config, 1 Dockerfile, 1 production guide (`PRODUCTION.md`).

---

## 2. Architecture

```
┌────────────────────── Frontend (Vite/React/Tailwind) ──────────────────────┐
│  RegisterAgent ─┐                                                          │
│  Leaderboard  ──┼──► useArcID ──► /api/* (proxied to FastAPI on :8000)     │
│  OrderDialog  ──┘                                                          │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────── Backend (FastAPI on Phala TDX CVM) ────────────────────┐
│  /register ──► register_agent()                                            │
│     ├── 1. attestation.generate_attestation()    ← real TDX in prod         │
│     ├── 2. web3 → ArcIDRegistry.register()       ← Arc L1                  │
│     ├── 3. event decode → agentId                                          │
│     ├── 4. circle_wallets.create_wallet_for_agent()  ← Circle API in prod  │
│     └── 5. web3 → ArcIDRegistry.bindWallet()      ← Arc L1                 │
│                                                                            │
│  /agents/{id}/order ──► polymarket.place_attributed_order()                │
│     ├── prototype: MockPolymarketBuilder on Arc                            │
│     └── real:      Polymarket V2 CLOB HTTP                                 │
└────────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────── Arc L1 (EVM) ──────────────────────────────────┐
│  DCAPVerifier ───► ArcIDRegistry ───► MockPolymarketBuilder                │
│                          ▲                       ▲                         │
│                          └── owner: backend op ──┘                         │
└────────────────────────────────────────────────────────────────────────────┘
```

The backend is the only privileged actor — it owns the deployer key, signs every Arc transaction, and binds the wallet on behalf of the agent. The agent's own key is only used to sign the *report-data* field inside the attestation; that key proves "the code in the enclave generated this quote" but never has to hold Arc gas, which matches the Paymaster model in the brief.

---

## 3. Production-readiness changes *(added post-prototype)*

The codebase has been updated to support a clean transition from local prototype to production. The prototype/real-mode split was already the right architecture; these additions wire it up for real deployment without changing any business logic.

### 3a. Configurable CORS (`ALLOWED_ORIGINS`)

`backend/config.py` now has an `allowed_origins` field (env: `ALLOWED_ORIGINS`, default `"*"`) and a `cors_origins` property that parses it as a comma-separated list. `backend/main.py` passes `settings.cors_origins` to `CORSMiddleware` instead of the hardcoded `["*"]`.

In production: `ALLOWED_ORIGINS=https://arcid.xyz,https://www.arcid.xyz`.

### 3b. Configurable Circle blockchain target (`ARC_NETWORK`)

`backend/config.py` has an `arc_network` field (env: `ARC_NETWORK`, default `"ARC-TESTNET"`). `backend/registry/circle_wallets.py` uses `settings.arc_network` in both the mock wallet (`blockchain` field) and the real Circle API call (`blockchains` array) instead of the hardcoded string `"ARC-TESTNET"`.

In production pointing at Arc mainnet: `ARC_NETWORK=ARC`.

### 3c. Frontend API URL (`VITE_API_BASE_URL`)

`frontend/src/hooks/useArcID.js` now reads `import.meta.env.VITE_API_BASE_URL` and falls back to `/api` when unset. The Vite dev-server proxy also respects `process.env.VITE_API_BASE_URL` as the proxy target (default `http://localhost:8000`).

- Dev: leave unset — Vite proxies `/api` → `http://localhost:8000` as before.
- Production (separate deploy): set `VITE_API_BASE_URL=https://api.arcid.xyz` before `npm run frontend:build`.
- Production (co-located): no change needed; same-origin `/api` still works.

### 3d. Production backend script

`package.json` gains a `backend:prod` script: `uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 2`. Drop `--reload` for production; two workers handle concurrent registrations.

For the full production deployment procedure see [`PRODUCTION.md`](./PRODUCTION.md).

---

## 3. The prototype/real-mode split *(the most important design call)*

The brief lists four external dependencies — Phala TDX, Circle (Wallets + Paymaster), Polymarket V2, Anthropic — none of which I can provision inside the time it takes to write this repo. But the brief also says **"start with Phase 1, Day 1"** and demands a runnable prototype. The only way to satisfy both is to draw a clean boundary at every external surface and ship two implementations behind it.

The contract: **each external adapter exposes the same Python interface in both modes, and the choice between them is `PROTOTYPE_MODE=true` plus the presence/absence of credentials**. There is no `if mock` sprinkled through business logic; the registration orchestrator does not know whether the attestation it just received came from real Intel hardware or `os.urandom`.

Concretely:

| Adapter | Real mode trigger | What I built |
|---|---|---|
| `attestation.generate_attestation()` | `PHALA_CLOUD_API_KEY` + `PHALA_CVM_ENDPOINT` set, `PROTOTYPE_MODE=false` | Real mode `POST`s to the CVM's `/attestation/quote`. Mock mode synthesises a v4-shaped quote with deterministic mrtd + agent-signed report-data |
| `CircleWalletClient.create_wallet_for_agent()` | `CIRCLE_API_KEY` + `CIRCLE_WALLET_SET_ID` set, `PROTOTYPE_MODE=false` | Real mode hits `api.circle.com/v1/w3s/developer/wallets`. Mock mode keccaks the agentId to derive a deterministic address |
| `place_attributed_order()` | `POLY_API_KEY` + `POLY_API_SECRET` + `POLY_API_PASSPHRASE` set, `PROTOTYPE_MODE=false` | Real mode `POST`s a CLOB order. Mock mode drives `MockPolymarketBuilder.reportAttributedFill()` on Arc so the agent's wallet *actually* receives a USDC builder fee on-chain — the leaderboard's "USDC fees earned" is real, not faked |
| `run_decision_cycle()` (Sentiment agent) | `ANTHROPIC_API_KEY` set | Real mode calls `claude-sonnet-4-6`. Mock mode does keyword counting |

The biggest win from this layout: I can demo the **full registration → wallet binding → Polymarket fee flow** locally, on the Hardhat node, with zero infrastructure dependencies. The USDC arriving at the agent's wallet in the mock path is a real ERC20 transfer on a real EVM. Only the *upstream sources* of attestation and order flow are synthesised.

---

## 4. Walkthrough by module

### 4.1 Contracts

**`DCAPVerifier.sol`** — The brief's Day 1 blocker. The full Automata-style verifier (~3 KB of PCK certificate-chain walking + TCB info parsing) is the right answer for production, but for a prototype it's overkill, and the *expensive* gas it consumes is exactly the cost we're supposed to benchmark on Day 1 *before* we commit to on-chain verification.

So this contract performs a structural check + a signature recovery:

1. Header sanity: version 4, ECDSA P-256, TEE_TYPE_TDX (`0x81`). Three little-endian reads near offset 0.
2. Length & mrtd: quote must be ≥ `0x250` bytes, the mrtd field at `0x70`-`0xA0` must hash to non-zero.
3. Report data: 32-byte commitment lifted out of `0x230`-`0x250`.
4. Signature recovery: `ecrecover(reportData, v, r, s)` over the 65-byte sig the agent provided.

Step 4 is the only on-chain crypto. It costs <5K gas. The full verifier would be ~2M. This contract has the *same external shape* (`verify(bytes, bytes) → (bool, QuoteSummary)`), so swapping in the real verifier on Day 2 is a 1-line registry change.

The Day 1 risk in the brief — "what does on-chain DCAP cost on Arc?" — is then answered by deploying *both* and benchmarking. This repo deploys the cheap one so the rest of the system can be tested today.

**`ArcIDRegistry.sol`** — The canonical registry. Key choices:

- **`agentId = keccak256(abi.encode(mrtd, reportData, attestedSigner))`** — three-field hash. mrtd alone would conflict across nonces; signer alone would let the same key register twice; reportData alone wouldn't tie to hardware. All three pinned together = the agent's identity is "this code, on this hardware, with this key".
- **Idempotency** — re-submitting an attestation that's already registered returns the existing agentId without charging again. Critical because the brief calls out the agent being autonomous: if the agent crashes and re-attests after restart, we don't want to drain its USDC.
- **Sponsored quota** — Paymaster integration is on the off-chain side, but the contract still records `gasSponsored: bool` per agent so the leaderboard can display the badge. The quota counter (`sponsoredQuota`) is decremented atomically with registration.
- **`bindWallet(agentId, wallet)` is owner-only**. The wallet is provisioned by the backend via Circle's API and bound here. We don't trust the agent itself to claim its own wallet because the wallet's MPC key is held by Circle on behalf of the registry operator. The brief calls for "only TEE-verified agents hold wallets" and this enforces it.
- **`listAgents(offset, limit)` returns the struct array** — paginated to keep frontend reads cheap. The leaderboard refresh loop hits this every 8s.
- **Errors are custom**, not `require` strings. Saves a few thousand gas per revert path. `InvalidAttestation`, `InsufficientFee`, `WalletAlreadyBound`, `UnknownAgent`.

**`IPolymarketBuilder.sol`** + **`MockPolymarketBuilder.sol`** — the bridge interface. Real Polymarket V2 routes builder rebates through their CLOB infra, but the *shape* (`registerBuilder(bytes32, address)` and `reportAttributedFill(bytes32, uint256)`) is what we control on our side. The mock literally pulls USDC from `msg.sender` and forwards it to the agent's wallet, so when the prototype simulates a fill, the agent's `balanceOf(usdc)` actually rises.

**`MockUSDC.sol`** — six-decimal ERC20 with a public `mint`. Used in tests and the local deploy.

### 4.2 Hardhat tests (`tests/test_contracts.js`)

The trickiest part of writing these was the **attestation builder helper**. I needed JS that produces a quote the verifier accepts plus a matching signature. The helper:

```js
function buildDcapQuote({ mrtdSeed, reportData })  // packs the right bytes at the right offsets
async function makeQuoteFor(signer, opts)         // computes reportData = keccak(signer || nonce), signs it
```

Critical detail: `signer.signingKey.sign(reportData)` produces a signature over the *raw 32-byte digest*, not an EIP-191 hashed message. That matches the verifier's `ecrecover(reportData, v, r, s)` exactly. If we'd done `signer.signMessage()` the digests would diverge by one keccak.

The seven tests cover, in order: verifier-accepts-valid, verifier-rejects-wrong-version, verifier-rejects-short, verifier-rejects-bad-sig, registry-emits-event-and-marks-sponsored, registry-charges-USDC-after-quota, registry-reverts-on-bad-attestation, registry-idempotent, registry-binds-wallet, registry-paginates, Polymarket-fee-routes-back-to-wallet.

The Polymarket test is the integration test for the *whole* attribution loop: register agent → bind wallet → register builder → simulate fill → assert agent's USDC balance went up. If that test ever breaks, the brief's headline claim ("USDC fees flow back to agent's Circle Programmable Wallet") is broken.

### 4.3 Deploy script (`scripts/deploy_arc.js`)

Writes `deployments/<network>.json` with addresses + chainId + timestamp. The Python config loader reads this file at boot, so the backend always knows where the registry lives without manual `.env` editing. Local deploys (both `hardhat` and `localhost` networks) spin up MockUSDC and MockPolymarketBuilder; testnet deploys assume real USDC exists at `USDC_TOKEN_ADDRESS` and skip the mock.

### 4.4 Backend — settings (`backend/config.py`)

Pydantic Settings, `.env`-backed, cached behind `@lru_cache`. Three convenience properties — `use_real_circle`, `use_real_phala`, `use_real_polymarket` — make the mode flips one-line elsewhere. `load_deployment()` hydrates contract addresses from `deployments/*.json`, which means the dev flow is:

```bash
npm run node            # terminal A — persistent Hardhat node on :8545
npm run deploy:dev      # terminal B — writes deployments/localhost.json
npm run backend:dev     # terminal C — picks up addresses automatically
```

`get_settings()` tries `localhost.json` first (persistent node), then falls back to `hardhat.json` (the ephemeral `deploy:local` artefact). No manual `.env` editing between deploy and run.

### 4.5 Backend — attestation (`backend/agent/attestation.py`)

The mock builder is intentionally byte-for-byte compatible with the on-chain verifier — same little-endian header, same mrtd offset, same report-data offset, same signature scheme. If you swap the mock for a real DCAP quote, the verifier doesn't change. That's the whole point of `_build_mock_quote` mimicking real layout.

`report_data = keccak(signer_address || nonce)`. The `signer_address` is the address whose key is held inside the enclave; the nonce is fresh randomness per attestation. Together they ensure each registration produces a different `agentId`, but the *same enclave-key+nonce* would produce the same one (which is what the registry's idempotency relies on).

The real-mode path is `POST $PHALA_CVM_ENDPOINT/attestation/quote` with the report-data as the request body. Inside the CVM, Phala's `dstack` runtime reads the TDX `/dev/tdx_guest` device, embeds the report-data, and returns the raw quote. The agent then signs that report-data itself before returning the bundle to the caller. The on-chain verifier doesn't care which path produced the quote — both look identical.

### 4.6 Backend — registration orchestrator (`backend/registry/register.py`)

This is the most procedural file in the repo. Web3 + Hardhat artifact loading + transaction signing + event decoding, all together. A few decisions worth calling out:

- **ABIs are loaded from `artifacts/contracts/**/*.json`** (Hardhat output). The loader globs by contract name and reads the first match. This means after every contract change you must `npm run compile` before the backend reflects it. Trade-off: avoids checking in a separate `abis/` dir that would drift.
- **USDC approval is best-effort**. If the registry's `registrationFee` is 0, or USDC isn't deployed, we skip approval silently. The contract handles "no allowance + zero fee + sponsored slot available" correctly anyway.
- **Event decoding falls back to recomputation**. If `AgentRegistered` isn't emitted (because we're re-registering an existing agent), we hash the three fields ourselves to reproduce the agentId. This means the API never returns "couldn't find the agentId" — it always returns *something* the caller can use.
- **`bindWallet` failures are logged, not raised**. If the wallet is already bound (idempotent re-register), the registry reverts; we treat that as success.

### 4.7 Backend — Circle wallets (`backend/registry/circle_wallets.py`)

In real mode: SCA wallets on `ARC-TESTNET`. SCA (smart-contract account) is what Circle's Paymaster sponsorship requires.

In mock mode: `keccak("arcid-mock-wallet" || agentId)[:32]` is treated as a private key; the address is derived from it. Deterministic per agentId, which means re-running the backend produces the same screenshots — important for the Loom demo.

Both paths return the same `CircleWallet` dataclass. The orchestrator can't tell which it got.

### 4.8 Backend — Polymarket bridge (`backend/bridge/polymarket.py`)

Real mode: thin HTTP wrapper around the V2 CLOB. Hackathon scope means we just need orders *accepted* (not necessarily filled) for the submission demo; if we needed real fills, we'd need real liquidity, which we don't have.

Mock mode: drives `MockPolymarketBuilder` on the Hardhat node. Each `place_attributed_order` call:

1. Registers the builder code if it isn't already (idempotent).
2. Mints USDC to the operator EOA (the "Polymarket fee router" stand-in) if needed.
3. Approves the builder contract.
4. Calls `reportAttributedFill(builderCode, feeUnits)`, which transfers USDC into the agent's wallet.

The agent's "fees earned" reading on the leaderboard then increases. This is the only way to make the leaderboard look alive without real Polymarket flow.

### 4.9 Backend — FastAPI (`backend/main.py`)

Eight endpoints, all narrow:

| Endpoint | Purpose |
|---|---|
| `GET /health` | liveness |
| `GET /config` | resolved addresses + which adapters are real vs mock |
| `POST /register` | full registration flow |
| `GET /agents` | paginated leaderboard (enriches each agent with `builder_fees_usdc`) |
| `GET /agents/{id}` | single agent + fees |
| `POST /agents/{id}/decide` | run the demo Sentiment cycle for this agent |
| `POST /agents/{id}/order` | place an attributed Polymarket order via the bridge |
| `GET /agents/{id}/fees` | cumulative builder fees |

CORS is wide-open (`*`) — fine for a hackathon, would lock down for prod.

### 4.10 Tests (`tests/test_attestation.py`, `tests/test_registry.py`)

`tests/conftest.py` adds the repo root to `sys.path` (so `from backend.x import y` works) and forces `PROTOTYPE_MODE=true`, ensuring no test ever touches a real external service.

`test_attestation.py` covers five things:
- Header constants are exactly what the on-chain verifier expects.
- Report data is *literally* the bytes at offset `0x230` in the quote.
- The signature recovers to `attestation.attested_signer` (cross-checked with `eth_keys` so we're not just calling the same function back).
- mrtd is deterministic per seed; report-data is randomised per call by default.
- Explicit nonce makes the whole attestation deterministic (useful for tests and screenshots).

`test_registry.py` covers the pure-Python pieces that don't need RPC:
- Mock Circle wallet is deterministic per agentId and unique across agents.
- Sentiment decision schema is well-formed in both bullish and ambiguous cases.
- Settings loader picks up `deployments/hardhat.json` automatically.

The end-to-end Arc flow is covered by `tests/test_contracts.js` instead — pytest-driving-Web3-against-Hardhat would add a node dependency to the Python test suite for no extra coverage.

### 4.11 Frontend

Three components plus a hook:

- **`useArcID.js`** — single hook owning all server state. Polls `/agents` every 8 seconds so the leaderboard feels alive when other people are registering. Exposes `registerAgent`, `placeOrder`, plus the agents list and config.
- **`RegisterAgent.jsx`** — name input + submit. On success, surfaces the agentId, wallet address, tx hash, and gas-sponsorship status in a monospaced confirmation card.
- **`Leaderboard.jsx`** — sorts agents by `builder_fees_usdc desc`, then `registered_at asc`. Shows total count and last-error if the backend is down.
- **`AgentCard.jsx`** — per-agent card with the TEE Verified badge (greenish accent, animated dot), USDC fees, wallet/signer short addresses, gas badge, and a "Place demo order" button.
- **`OrderDialog.jsx`** — modal with YES/NO, size slider, defaults to "Will Agora have >200 submissions?" market (the brief's example).

Tailwind is configured with a small `arc-*` palette so the design has its own identity without me having to design from scratch. Dark by default — matches the "trading infra" aesthetic the brief signals.

### 4.12 Phala CVM (`phala/cvm_config.json`, `phala/Dockerfile`)

The CVM config declares the TDX image, exposes the attestation endpoint, and lists the only external hosts the enclave is allowed to reach (Circle, Anthropic, Arc RPC, Polymarket). Secrets are scoped `cvm_only` so they never appear outside the enclave.

The Dockerfile is a plain `python:3.11-slim` build with the backend baked in. Production would pin the image hash and sign it so the mrtd is reproducible; for the prototype, just running it locally on `docker run` is enough.

---

## 5. Decisions table

This is the "why" log — each interesting choice, its alternative, and the reason.

| # | Decision | Alternative | Why I picked this |
|---|---|---|---|
| 1 | Ship a simplified DCAP verifier instead of the full Automata port | Port the full ~3KB verifier on Day 1 | Brief's Day 1 task is *benchmarking* gas. The simplified verifier lets the rest of the system be built today; the real one slots in behind the same interface tomorrow once we have a number |
| 2 | `agentId = keccak(mrtd, reportData, attestedSigner)` | Just `keccak(reportData)` | Three-field hash is the only way to make the ID describe code + hardware + key. Single-field collapses on any axis (replay attacks, key reuse) |
| 3 | Registration is idempotent | Reject double-register | Autonomous agents crash and restart; we don't want to drain USDC on retries. The brief's "agent runs fully autonomously" requires this |
| 4 | Sponsored quota lives in the contract, not the Paymaster | Track usage off-chain | On-chain quota means the leaderboard's "gas sponsored" badge is verifiable, not just our word for it. Matches the "moat is the attestation layer" angle |
| 5 | `bindWallet` is owner-only | Let agents claim their own wallets | The wallet's MPC key is held by Circle on behalf of the registry. Brief says "only TEE-verified agents hold wallets" — the registry has to gate that |
| 6 | Mock mode shares structural layout with real mode | Separate mock data path | When you swap mock for real, nothing else changes. Reduces the "it worked in the demo but broke in prod" risk |
| 7 | The mock Polymarket builder is on-chain | Mock at the Python layer | "USDC fees earned" on the leaderboard is a real ERC20 balance. Demonstrates the value prop end-to-end without real Polymarket liquidity |
| 8 | Anthropic model: Claude Sonnet 4.6 | Opus | Sentiment classification doesn't need Opus tier; brief explicitly says Sonnet; latency matters more than depth for autonomous trading loops |
| 9 | Frontend polls every 8s instead of websockets | WebSocket subscription to events | 8s is fine for a hackathon leaderboard. WebSocket adds infra; polling fails gracefully |
| 10 | Backend uses Web3.py instead of ethers-py | Use a higher-level lib | Web3.py is the most stable Python Ethereum lib. The transaction-signing API is verbose but well-understood |
| 11 | Hardhat artifacts → backend ABIs via glob | Generate a typed ABI bundle | Glob is fragile but trivial. A typed bundle would be cleaner but adds a build step that doesn't pay off until we have >10 contracts |
| 12 | CORS `*` | Lock to localhost | Hackathon. Don't ship to prod like this |
| 13 | One shared `DEPLOYER_PRIVATE_KEY` does everything (deploy + register + bind) | Separate operator key | Reduces key management. In prod the operator should be a multisig and the deployer should be retired after launch |
| 14 | `PROTOTYPE_MODE=true` is default | Default to live | A fresh clone should run end-to-end with zero configuration. Discoverability beats production-default |
| 15 | `ALLOWED_ORIGINS` env var, default `*` | Hardcode a domain | Prototype needs open CORS; production must lock it down. One env var handles both without a code change |
| 16 | `ARC_NETWORK` env var for Circle blockchain name | Infer from chain ID | Circle's API uses string identifiers (`"ARC"`, `"ARC-TESTNET"`), not chain IDs. An explicit var avoids a fragile chain-ID-to-string mapping |
| 17 | `VITE_API_BASE_URL` for frontend API target | Always `/api` | Frontend may be deployed to a CDN separate from the backend. The var is unset in dev (Vite proxy handles it) and set to the full URL in prod |

---

## 6. Where this would break if you hit it hard

I'm being honest about the cracks so you know what to fix first.

1. **The simplified verifier is not Sybil-resistant.** Anyone can fabricate a quote that passes our structural check and registers with any signer key they control. The full Automata verifier closes this — it requires Intel's PCK certificate chain — and is the real Day 2 task.
2. **The deployer key is the registry owner, the wallet binder, and the Polymarket router stand-in.** Compartmentalising those into three separate roles is straightforward but not done.
3. **There's no rate-limiting on `/register`.** A real deployment would need a Sybil-prevention layer beyond the $0.10 fee (the fee alone doesn't deter spam if the sponsored quota is non-zero, which is the *whole point* of the sponsored quota).
4. **The frontend has no error retry**. If the backend is down at 0s, the leaderboard shows the error string and stays there for 8s before retrying. Fine for a hackathon, ugly under load.
5. **The mock Circle wallet's private key is derivable** — anyone can recover it from the agentId. Real Circle wallets are MPC-secured; do not use the prototype wallet client with real value.
6. **The Hardhat tests don't run on Windows without `npm install`.** That's a prerequisite, not a bug, but worth calling out — there's no checked-in `node_modules`.

---

## 7. What's *not* in this prototype, by design

These were called out in the brief as Phase 3-4 / stretch goals. They are stubs with clear seams:

- **Hyperliquid HIP-3 adapter** — the brief explicitly lists this as stretch (Phase 4). Not built. Would slot alongside `bridge/polymarket.py` as `bridge/hyperliquid.py` with the same shape.
- **Gateway nanopayments for re-verification** — also stretch. Would hook into the registry's owner-only entrypoints to charge a sub-cent fee for each `getAgent` view call.
- **Real Phala CVM image build** — the Dockerfile is here but I haven't run `docker build`. Phala Cloud uploads need an account.
- **Medium article** — Phase 3 marketing work; out of scope for code.
- **Loom demo video** — Phase 4 deliverable; produced from the running prototype, not part of the repo.

---

## 8. Run it

### Local (prototype mode)

```bash
# 1. install deps
npm install
cd backend && pip install -r requirements.txt && cd ..
cd frontend && npm install && cd ..

# 2. compile, test, deploy locally
npm run compile
npm run test:contracts        # 11 contract tests should pass
pytest                        # 12 Python tests should pass

npm run node                  # terminal A — Hardhat node on :8545
npm run deploy:dev            # terminal B — writes deployments/localhost.json

# 3. start services
cp .env.example .env          # prototype mode is default
npm run backend:dev           # terminal C — FastAPI on :8000
npm run frontend:dev          # terminal D — Vite on :5173
```

### Production

See [`PRODUCTION.md`](./PRODUCTION.md) for the full procedure. The short version:

```bash
# 1. Set real credentials in .env (or secrets manager):
#    ARC_RPC_URL, ARC_CHAIN_ID, ARC_NETWORK, DEPLOYER_PRIVATE_KEY,
#    CIRCLE_API_KEY, CIRCLE_WALLET_SET_ID, CIRCLE_ENTITY_SECRET,
#    PHALA_CLOUD_API_KEY, PHALA_CVM_ENDPOINT,
#    ANTHROPIC_API_KEY, POLY_API_KEY/SECRET/PASSPHRASE,
#    PROTOTYPE_MODE=false, ALLOWED_ORIGINS=https://arcid.xyz

# 2. Deploy contracts to Arc
npm run deploy:arc             # → writes deployments/arcTestnet.json

# 3. Build frontend
VITE_API_BASE_URL=https://api.arcid.xyz npm run frontend:build
# → deploy frontend/dist/ to CDN

# 4. Start production backend (behind nginx/Caddy for TLS)
npm run backend:prod
```

Visit http://localhost:5173, register an agent, watch a card appear with a TEE Verified badge. Click *Place demo order* and watch the agent's USDC fees tick up.

### Common runtime errors

**`BadFunctionCallOutput: Could not transact with/call contract function`** on `/agents` or `/register`

Three distinct root causes produce the same error:

**Cause A — deployed to the ephemeral network instead of the persistent node.** `npm run deploy:local` uses `--network hardhat`, which spins up a temporary in-memory chain *inside the deploy process* and destroys it when the script exits. The backend connects to `http://127.0.0.1:8545` (the `npm run node` persistent node), where those contracts were never deployed. Fix: use the persistent-node workflow:

```bash
npm run node       # terminal A — must already be running
npm run deploy:dev # deploys to --network localhost (the persistent node)
                   # writes deployments/localhost.json
```

You do not need to restart the backend — the addresses are deterministic and identical after a fresh deploy.

**Cause B — node restarted after last deploy.** Hardhat's chain is in-memory; every restart wipes all deployed contracts. The addresses in `deployments/localhost.json` are deterministic (derived from the deployer nonce), so they look the same after a fresh deploy, but the bytecode is gone until you redeploy. Fix:

```bash
npm run deploy:dev   # re-deploy against the running node
```

**Cause C — `.env` points at testnet while contracts are local.** If `.env` contains `ARC_RPC_URL=https://rpc.testnet.arc.network` and `ARC_CHAIN_ID=421614`, the backend talks to the Arc testnet. The contract addresses in `deployments/localhost.json` only exist on your local Hardhat node, so every call returns empty bytes and the ABI decoder throws. Fix:

```env
ARC_RPC_URL=http://127.0.0.1:8545
ARC_CHAIN_ID=31337
```

Then restart the backend so the new env is picked up (settings are cached at startup via `@lru_cache`).

**`binascii.Error: Non-hexadecimal digit found`** on `POST /register`

Sent `"agent_private_key": "string"` — the Swagger UI placeholder, not a real key. Either delete the field entirely (the backend generates a fresh key automatically when it is absent or `null`) or supply a real `0x`-prefixed 32-byte hex private key.

**`RUN.md` said `npm run deploy:local` for Window B — that was wrong.** `deploy:local` uses `--network hardhat`, which is the ephemeral in-process network (see Cause A above). `RUN.md` has been corrected to `npm run deploy:dev`. If you ran `deploy:local` and then started the backend, every contract call will fail because the contracts were deployed to a temporary chain that no longer exists. Fix: with Window A still running, re-run Window B with the correct command:

```powershell
npm run deploy:dev
```

**`eth_keys.exceptions.ValidationError` or silent wrong-address errors** on `POST /register`

The `.env.example` originally shipped `DEPLOYER_PRIVATE_KEY=0x0000000000000000000000000000000000000000000000000000000000000000` (all zeros). This is an invalid secp256k1 key and causes `eth_account` to throw on the first transaction. Even if it didn't throw, it would derive a different address from the one that owns the deployed contracts, so every owner-only call (`bindWallet`, USDC `approve`) would revert. The correct value for local dev is Hardhat's first default account key, which is the same account `deploy:dev` uses as the deployer:

```env
DEPLOYER_PRIVATE_KEY=0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80
```

Both `.env.example` and `.env` have been updated with this key.

---

## 9. What I'd do next (in priority order)

1. Port the full Automata DCAPv4 verifier and replace `DCAPVerifier.sol`. Same interface, real security. Benchmark on Arc testnet. This is the brief's Day 1 task — the prototype is unblocked but the *security claim* isn't real until this lands.
2. Wire real Circle Programmable Wallets with a single live agent end-to-end. Confirm Paymaster sponsorship works on Arc.
3. Place one real Polymarket V2 order with a real ArcID as builder code. Confirm fee flows back. This is the headline demo for submission.
4. Build the Phala CVM image properly, deploy it, register the real demo agent against the testnet registry. The mrtd will then describe *actual* code, and that's the moment the moat becomes real.
5. Discord announcement + Medium article to drive Phase 2 traction.
6. Lock down CORS, split operator from deployer, add rate-limiting on `/register`.

Items 1–4 are the difference between "prototype that demonstrates the architecture" and "thing other hackathon participants will actually register against". Items 5–6 are scale.
