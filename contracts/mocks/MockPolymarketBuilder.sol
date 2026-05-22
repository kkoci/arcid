// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {IPolymarketBuilder} from "../interfaces/IPolymarketBuilder.sol";

/// @notice Local stand-in for the Polymarket V2 builder-code contract.
///         Implements the same interface so the bridge layer is identical in
///         tests and on testnet — only the deployed address differs.
contract MockPolymarketBuilder is IPolymarketBuilder {
    IERC20 public immutable usdc;
    mapping(bytes32 => address) public feeRecipientOf;
    mapping(bytes32 => uint256) public feesAccumulated;

    event BuilderRegistered(bytes32 indexed builderCode, address indexed feeRecipient);
    event FillReported(bytes32 indexed builderCode, uint256 usdcAmount);

    constructor(IERC20 _usdc) {
        usdc = _usdc;
    }

    function registerBuilder(bytes32 builderCode, address feeRecipient) external override {
        feeRecipientOf[builderCode] = feeRecipient;
        emit BuilderRegistered(builderCode, feeRecipient);
    }

    function reportAttributedFill(bytes32 builderCode, uint256 usdcAmount) external override {
        address recipient = feeRecipientOf[builderCode];
        require(recipient != address(0), "builder not registered");
        feesAccumulated[builderCode] += usdcAmount;
        // Pull USDC from the caller (simulating Polymarket's fee router) and
        // forward to the agent's wallet.
        require(usdc.transferFrom(msg.sender, recipient, usdcAmount), "fee xfer failed");
        emit FillReported(builderCode, usdcAmount);
    }

    function builderFeesEarned(bytes32 builderCode) external view override returns (uint256) {
        return feesAccumulated[builderCode];
    }
}
