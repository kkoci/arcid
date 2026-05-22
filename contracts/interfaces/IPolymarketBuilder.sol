// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title IPolymarketBuilder
/// @notice Minimal interface for the Polymarket V2 builder-code attribution flow.
///         An ArcID `bytes32` agentId is presented to Polymarket as a builder code so
///         that fills routed by the agent earn a portion of the venue fee, payable in
///         USDC back to the agent's Circle Programmable Wallet.
interface IPolymarketBuilder {
    /// @notice Register an ArcID-issued bytes32 as an accepted builder code.
    /// @param builderCode  The 32-byte agentId being attributed.
    /// @param feeRecipient The address that receives USDC builder rebates.
    function registerBuilder(bytes32 builderCode, address feeRecipient) external;

    /// @notice Report that an order has settled and credit the agent's accumulated fees.
    /// @param builderCode The agentId that originated the attribution.
    /// @param usdcAmount  Builder fee credited, denominated in USDC's 6-decimal base unit.
    function reportAttributedFill(bytes32 builderCode, uint256 usdcAmount) external;

    /// @notice View accumulated USDC builder fees earned by an agent.
    function builderFeesEarned(bytes32 builderCode) external view returns (uint256);
}
