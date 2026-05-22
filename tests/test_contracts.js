/* eslint-disable no-undef */
const { expect } = require("chai");
const { ethers } = require("hardhat");

// Hardhat's built-in network funds 20 accounts derived from this mnemonic.
// We re-derive them as HDNodeWallet (instead of using ethers.getSigners(),
// which returns HardhatEthersSigner — that wrapper hides the private key, so
// signingKey.sign(digest) is undefined). HDNodeWallet exposes .signingKey,
// which the DCAP test helpers need to sign a raw 32-byte digest.
const HARDHAT_MNEMONIC =
  "test test test test test test test test test test test junk";
function walletAt(i) {
  return ethers.HDNodeWallet.fromPhrase(
    HARDHAT_MNEMONIC,
    undefined,
    `m/44'/60'/0'/0/${i}`
  ).connect(ethers.provider);
}

// ---------------------------------------------------------------------------
// helpers — build a DCAP quote whose structural fields the prototype verifier
// accepts, plus a matching signature over the report-data field.
// ---------------------------------------------------------------------------
function buildDcapQuote({ mrtdSeed = "mrtd-seed", reportData }) {
  // Allocate a 0x250-byte buffer. Verifier reads:
  //   0x00-0x02 : version       (u16 LE) → 4
  //   0x02-0x04 : att key type  (u16 LE) → 2
  //   0x04-0x08 : tee type      (u32 LE) → 0x81
  //   0x70-0xA0 : mrtd (48 bytes) — must hash to non-zero
  //   0x230-0x250 : report_data (32 bytes prefix is what the verifier slices)
  const buf = Buffer.alloc(0x250);
  buf.writeUInt16LE(4, 0x00);
  buf.writeUInt16LE(2, 0x02);
  buf.writeUInt32LE(0x81, 0x04);

  const mrtd = ethers.getBytes(ethers.keccak256(ethers.toUtf8Bytes(mrtdSeed)));
  // pad to 48 bytes
  const mrtd48 = Buffer.alloc(48);
  Buffer.from(mrtd).copy(mrtd48, 0);
  mrtd48.copy(buf, 0x70);

  const rd = ethers.getBytes(reportData);
  Buffer.from(rd).copy(buf, 0x230);

  return "0x" + buf.toString("hex");
}

async function makeQuoteFor(signer, { mrtdSeed = "mrtd-seed", nonce = "0xdead" } = {}) {
  const reportData = ethers.keccak256(
    ethers.solidityPacked(["address", "bytes"], [await signer.getAddress(), nonce])
  );
  const quote = buildDcapQuote({ mrtdSeed, reportData });
  // Sign the raw 32-byte digest (NOT EIP-191), matching the verifier's
  // ecrecover(reportData, v, r, s) call.
  const sigFlat = signer.signingKey.sign(reportData);
  const sig = ethers.concat([sigFlat.r, sigFlat.s, ethers.toBeArray(sigFlat.v)]);
  return { quote, sig, reportData };
}

// ---------------------------------------------------------------------------

describe("DCAPVerifier", function () {
  let verifier;
  let agent;

  beforeEach(async () => {
    agent = walletAt(1);
    const Verifier = await ethers.getContractFactory("DCAPVerifier");
    verifier = await Verifier.deploy();
  });

  it("accepts a well-formed quote and recovers the signer", async () => {
    const { quote, sig } = await makeQuoteFor(agent);
    const [ok, summary] = await verifier.verify(quote, sig);
    expect(ok).to.equal(true);
    expect(summary.attestedSigner).to.equal(await agent.getAddress());
    expect(summary.teeType).to.equal(0x81);
  });

  it("rejects a quote with the wrong version", async () => {
    const { quote, sig } = await makeQuoteFor(agent);
    // flip version byte
    const bad = "0x05" + quote.slice(4);
    const [ok] = await verifier.verify(bad, sig);
    expect(ok).to.equal(false);
  });

  it("rejects a short quote", async () => {
    const short = "0x" + "00".repeat(0x100);
    const sig = "0x" + "00".repeat(65);
    const [ok] = await verifier.verify(short, sig);
    expect(ok).to.equal(false);
  });

  it("rejects a wrong-length signature", async () => {
    const { quote } = await makeQuoteFor(agent);
    const [ok] = await verifier.verify(quote, "0xdead");
    expect(ok).to.equal(false);
  });
});

describe("ArcIDRegistry", function () {
  const FEE = 100_000n; // 0.10 USDC (6 decimals)
  const QUOTA = 2n;

  let owner, treasury, agentA, agentB, polyRouter;
  let usdc, verifier, registry, builder;

  beforeEach(async () => {
    owner = walletAt(0);
    treasury = walletAt(1);
    agentA = walletAt(2);
    agentB = walletAt(3);
    polyRouter = walletAt(4);

    const USDC = await ethers.getContractFactory("MockUSDC");
    usdc = await USDC.deploy();

    const Verifier = await ethers.getContractFactory("DCAPVerifier");
    verifier = await Verifier.deploy();

    const Registry = await ethers.getContractFactory("ArcIDRegistry");
    registry = await Registry.deploy(
      await verifier.getAddress(),
      await usdc.getAddress(),
      FEE,
      QUOTA,
      await treasury.getAddress()
    );

    const Builder = await ethers.getContractFactory("MockPolymarketBuilder");
    builder = await Builder.deploy(await usdc.getAddress());
  });

  it("registers an agent with a valid attestation and consumes a sponsored slot first", async () => {
    const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: "agent-a" });

    const tx = await registry.connect(agentA).register(quote, sig, "Agent A");
    const rcpt = await tx.wait();

    const evt = rcpt.logs
      .map((l) => {
        try { return registry.interface.parseLog(l); } catch { return null; }
      })
      .find((p) => p && p.name === "AgentRegistered");
    expect(evt).to.not.be.undefined;
    expect(evt.args.gasSponsored).to.equal(true);
    expect(evt.args.attestedSigner).to.equal(await agentA.getAddress());
    expect(await registry.totalAgents()).to.equal(1n);
    expect(await registry.sponsoredQuota()).to.equal(QUOTA - 1n);
  });

  it("charges a USDC fee once the sponsored quota is exhausted", async () => {
    // Consume both sponsored slots
    for (const seed of ["seed-1", "seed-2"]) {
      const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: seed });
      await registry.connect(agentA).register(quote, sig, "spam");
    }
    expect(await registry.sponsoredQuota()).to.equal(0n);

    // Third registration requires payment
    const { quote, sig } = await makeQuoteFor(agentB, { mrtdSeed: "seed-3" });
    await usdc.mint(await agentB.getAddress(), FEE);
    await usdc.connect(agentB).approve(await registry.getAddress(), FEE);

    await registry.connect(agentB).register(quote, sig, "Agent B");
    expect(await usdc.balanceOf(await treasury.getAddress())).to.equal(FEE);
  });

  it("reverts when the attestation is malformed", async () => {
    const bogusQuote = "0x" + "00".repeat(0x250);
    const sig = "0x" + "00".repeat(65);
    await expect(
      registry.connect(agentA).register(bogusQuote, sig, "Bad")
    ).to.be.revertedWithCustomError(registry, "InvalidAttestation");
  });

  it("is idempotent — re-submitting the same quote does not charge twice", async () => {
    const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: "idem" });
    const tx1 = await registry.connect(agentA).register(quote, sig, "Agent A");
    const r1 = await tx1.wait();
    const id1 = r1.logs
      .map((l) => { try { return registry.interface.parseLog(l); } catch { return null; } })
      .find((p) => p && p.name === "AgentRegistered").args.agentId;

    // second call returns the same id and emits no second event
    await registry.connect(agentA).register(quote, sig, "Agent A again");
    expect(await registry.totalAgents()).to.equal(1n);
    const fetched = await registry.getAgent(id1);
    expect(fetched.name).to.equal("Agent A"); // name does NOT change
  });

  it("binds a wallet to an agent (operator only) and exposes it via getAgent", async () => {
    const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: "wallet-bind" });
    const tx = await registry.connect(agentA).register(quote, sig, "Walleted");
    const rcpt = await tx.wait();
    const agentId = rcpt.logs
      .map((l) => { try { return registry.interface.parseLog(l); } catch { return null; } })
      .find((p) => p && p.name === "AgentRegistered").args.agentId;

    const fakeWallet = "0x000000000000000000000000000000000000bEEF";
    await registry.connect(owner).bindWallet(agentId, fakeWallet);
    const a = await registry.getAgent(agentId);
    expect(a.wallet.toLowerCase()).to.equal(fakeWallet.toLowerCase());

    // second bind should revert
    await expect(
      registry.connect(owner).bindWallet(agentId, fakeWallet)
    ).to.be.revertedWithCustomError(registry, "WalletAlreadyBound");
  });

  it("paginates the leaderboard", async () => {
    // Quota was 2; bump it so all 4 registrations are gas-sponsored.
    await registry.connect(owner).topUpSponsoredQuota(2n);
    for (let i = 0; i < 4; i++) {
      const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: `n-${i}` });
      await registry.connect(agentA).register(quote, sig, `Agent ${i}`);
    }
    expect(await registry.totalAgents()).to.be.greaterThanOrEqual(2n);

    const page = await registry.listAgents(0, 10);
    expect(page.length).to.be.greaterThanOrEqual(2);
  });

  it("routes a Polymarket builder fill back to the agent's wallet", async () => {
    const { quote, sig } = await makeQuoteFor(agentA, { mrtdSeed: "poly" });
    const tx = await registry.connect(agentA).register(quote, sig, "Poly Agent");
    const rcpt = await tx.wait();
    const agentId = rcpt.logs
      .map((l) => { try { return registry.interface.parseLog(l); } catch { return null; } })
      .find((p) => p && p.name === "AgentRegistered").args.agentId;

    const walletAddr = await agentB.getAddress(); // stand-in for Circle PW
    await registry.connect(owner).bindWallet(agentId, walletAddr);

    await builder.connect(agentA).registerBuilder(agentId, walletAddr);

    const fee = 50_000n; // $0.05
    await usdc.mint(await polyRouter.getAddress(), fee);
    await usdc.connect(polyRouter).approve(await builder.getAddress(), fee);
    await builder.connect(polyRouter).reportAttributedFill(agentId, fee);

    expect(await usdc.balanceOf(walletAddr)).to.equal(fee);
    expect(await builder.builderFeesEarned(agentId)).to.equal(fee);
  });
});
