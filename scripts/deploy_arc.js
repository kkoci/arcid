/* eslint-disable no-undef */
// Deploy ArcID contracts to Arc testnet (or local Hardhat).
//
// Usage:
//   npx hardhat run scripts/deploy_arc.js --network arcTestnet
//   npx hardhat run scripts/deploy_arc.js --network hardhat
//
// Output: deployments/<network>.json with the deployed addresses, ABIs and
// block numbers. The backend reads this file at boot.

const fs = require("fs");
const path = require("path");
const hre = require("hardhat");

async function main() {
  const network = hre.network.name;
  const [deployer] = await hre.ethers.getSigners();
  console.log(`\n→ Deploying ArcID to ${network} as ${await deployer.getAddress()}`);

  // --- USDC: real address from .env on Arc, mock on local ---
  const isLocal = network === "hardhat" || network === "localhost";
  let usdcAddress = process.env.USDC_TOKEN_ADDRESS;
  if (isLocal || !usdcAddress || usdcAddress === hre.ethers.ZeroAddress) {
    const USDC = await hre.ethers.getContractFactory("MockUSDC");
    const usdc = await USDC.deploy();
    await usdc.waitForDeployment();
    usdcAddress = await usdc.getAddress();
    console.log(`   MockUSDC deployed → ${usdcAddress}`);
    // mint a stash to the deployer so they can register without help
    await (await usdc.mint(await deployer.getAddress(), 10_000_000_000n)).wait();
  } else {
    console.log(`   Using real USDC → ${usdcAddress}`);
  }

  // --- DCAPVerifier ---
  const Verifier = await hre.ethers.getContractFactory("DCAPVerifier");
  const verifier = await Verifier.deploy();
  await verifier.waitForDeployment();
  const verifierAddress = await verifier.getAddress();
  console.log(`   DCAPVerifier  deployed → ${verifierAddress}`);

  // --- ArcIDRegistry ---
  const FEE = 100_000n;         // $0.10 USDC
  const QUOTA = 100n;           // 100 gas-sponsored registrations
  const feeRecipient = await deployer.getAddress();

  const Registry = await hre.ethers.getContractFactory("ArcIDRegistry");
  const registry = await Registry.deploy(
    verifierAddress,
    usdcAddress,
    FEE,
    QUOTA,
    feeRecipient
  );
  await registry.waitForDeployment();
  const registryAddress = await registry.getAddress();
  console.log(`   ArcIDRegistry deployed → ${registryAddress}`);

  // --- MockPolymarketBuilder (only on local, where there's no real one) ---
  let builderAddress = null;
  if (isLocal) {
    const Builder = await hre.ethers.getContractFactory("MockPolymarketBuilder");
    const builder = await Builder.deploy(usdcAddress);
    await builder.waitForDeployment();
    builderAddress = await builder.getAddress();
    console.log(`   MockPolymarketBuilder → ${builderAddress}`);
  }

  // --- Persist deployment ---
  const deploymentDir = path.resolve(__dirname, "..", "deployments");
  if (!fs.existsSync(deploymentDir)) fs.mkdirSync(deploymentDir);
  const out = {
    network,
    chainId: Number((await hre.ethers.provider.getNetwork()).chainId),
    deployer: await deployer.getAddress(),
    timestamp: Math.floor(Date.now() / 1000),
    addresses: {
      USDC: usdcAddress,
      DCAPVerifier: verifierAddress,
      ArcIDRegistry: registryAddress,
      MockPolymarketBuilder: builderAddress,
    },
    config: {
      registrationFee: FEE.toString(),
      sponsoredQuota: QUOTA.toString(),
      feeRecipient,
    },
  };
  fs.writeFileSync(
    path.join(deploymentDir, `${network}.json`),
    JSON.stringify(out, null, 2)
  );
  console.log(`\n✓ Wrote deployments/${network}.json`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
