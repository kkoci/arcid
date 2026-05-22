require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

const ARC_RPC_URL = process.env.ARC_RPC_URL || "https://rpc.testnet.arc.network";
const ARC_CHAIN_ID = parseInt(process.env.ARC_CHAIN_ID || "421614", 10);
const DEPLOYER_PRIVATE_KEY =
  process.env.DEPLOYER_PRIVATE_KEY ||
  "0x0000000000000000000000000000000000000000000000000000000000000001";

module.exports = {
  solidity: {
    version: "0.8.24",
    settings: {
      optimizer: { enabled: true, runs: 200 },
      viaIR: true,
    },
  },
  networks: {
    hardhat: {
      chainId: 31337,
    },
    localhost: {
      url: "http://127.0.0.1:8545",
      chainId: 31337,
    },
    arcTestnet: {
      url: ARC_RPC_URL,
      chainId: ARC_CHAIN_ID,
      accounts: [DEPLOYER_PRIVATE_KEY],
    },
  },
  paths: {
    sources: "./contracts",
    tests: "./tests",
    cache: "./cache",
    artifacts: "./artifacts",
  },
  mocha: { timeout: 60000 },
};
