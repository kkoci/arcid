// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {Ownable} from "@openzeppelin/contracts/access/Ownable.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

import {DCAPVerifier} from "./DCAPVerifier.sol";

/// @title ArcIDRegistry
/// @notice Canonical registry of TEE-attested AI agents on Arc.
///         Issues a deterministic `bytes32 agentId` to any agent that submits
///         a DCAP attestation quote which the on-chain verifier accepts. The
///         agentId is also valid as a Polymarket V2 builder code.
///
///         Registration costs a flat USDC fee (default $0.10, 6-decimal token).
///         The Circle Programmable Wallet for the new agent is created off-chain
///         by the backend and recorded here via `bindWallet` from the registry
///         operator address — keeping wallet provisioning auditable on-chain
///         without forcing the wallet API into the contract.
///
/// @dev Design notes:
///   - agentId is `keccak256(abi.encode(mrtd, reportData, attestedSigner))`.
///     Same code + same key + same nonce → same agentId. Re-registering is a
///     no-op (returns the existing ID without charging twice).
///   - The first 100 registrations can be marked `gasSponsored`. The Paymaster
///     handles the actual gas; this contract just records the flag so the
///     leaderboard can show it.
///   - `feeRecipient` is the protocol treasury (DAO multisig in production).
contract ArcIDRegistry is Ownable, ReentrancyGuard {
    // ---------------------------------------------------------------------
    // types
    // ---------------------------------------------------------------------

    struct Agent {
        bytes32 agentId;
        bytes32 mrtd;             // hashed TDX measurement
        bytes32 reportData;       // commitment the enclave embedded
        address attestedSigner;   // key recovered from the DCAP sig
        address wallet;           // Circle Programmable Wallet address
        string  name;             // human-readable label
        uint64  registeredAt;
        bool    gasSponsored;
    }

    // ---------------------------------------------------------------------
    // storage
    // ---------------------------------------------------------------------

    DCAPVerifier public immutable verifier;
    IERC20 public immutable usdc;

    uint256 public registrationFee;          // 6-decimal USDC, e.g. 100_000 = $0.10
    uint256 public sponsoredQuota;           // remaining gas-sponsored slots
    address public feeRecipient;             // protocol treasury

    bytes32[] public allAgentIds;
    mapping(bytes32 => Agent) private _agents;
    mapping(address => bytes32) public agentIdBySigner;

    // ---------------------------------------------------------------------
    // events
    // ---------------------------------------------------------------------

    event AgentRegistered(
        bytes32 indexed agentId,
        address indexed attestedSigner,
        bytes32 mrtd,
        string  name,
        bool    gasSponsored,
        uint64  registeredAt
    );

    event WalletBound(bytes32 indexed agentId, address indexed wallet);
    event RegistrationFeeChanged(uint256 oldFee, uint256 newFee);
    event FeeRecipientChanged(address indexed oldRecipient, address indexed newRecipient);

    // ---------------------------------------------------------------------
    // errors
    // ---------------------------------------------------------------------

    error InvalidAttestation();
    error InsufficientFee();
    error WalletAlreadyBound();
    error UnknownAgent();

    // ---------------------------------------------------------------------
    // constructor
    // ---------------------------------------------------------------------

    constructor(
        DCAPVerifier _verifier,
        IERC20 _usdc,
        uint256 _registrationFee,
        uint256 _sponsoredQuota,
        address _feeRecipient
    ) Ownable(msg.sender) {
        verifier = _verifier;
        usdc = _usdc;
        registrationFee = _registrationFee;
        sponsoredQuota = _sponsoredQuota;
        feeRecipient = _feeRecipient;
    }

    // ---------------------------------------------------------------------
    // registration
    // ---------------------------------------------------------------------

    /// @notice Register an agent by submitting a DCAP attestation quote.
    /// @param dcapQuote      Raw quote bytes from the TDX hardware.
    /// @param reportDataSig  Agent signature over the quote's report-data field.
    /// @param name           Display label for the leaderboard.
    /// @return agentId Canonical bytes32 identifier.
    function register(
        bytes calldata dcapQuote,
        bytes calldata reportDataSig,
        string calldata name
    ) external nonReentrant returns (bytes32 agentId) {
        (bool ok, DCAPVerifier.QuoteSummary memory s) = verifier.verify(dcapQuote, reportDataSig);
        if (!ok) revert InvalidAttestation();

        agentId = keccak256(abi.encode(s.mrtd, s.reportData, s.attestedSigner));

        // Idempotent: re-registering the same quote returns the existing record.
        if (_agents[agentId].registeredAt != 0) {
            return agentId;
        }

        bool sponsored = false;
        if (sponsoredQuota > 0) {
            sponsoredQuota -= 1;
            sponsored = true;
        } else {
            // Pull the USDC fee from the caller. Caller must have approved.
            bool transferOk = usdc.transferFrom(msg.sender, feeRecipient, registrationFee);
            if (!transferOk) revert InsufficientFee();
        }

        _agents[agentId] = Agent({
            agentId: agentId,
            mrtd: s.mrtd,
            reportData: s.reportData,
            attestedSigner: s.attestedSigner,
            wallet: address(0),
            name: name,
            registeredAt: uint64(block.timestamp),
            gasSponsored: sponsored
        });
        allAgentIds.push(agentId);
        agentIdBySigner[s.attestedSigner] = agentId;

        emit AgentRegistered(
            agentId,
            s.attestedSigner,
            s.mrtd,
            name,
            sponsored,
            uint64(block.timestamp)
        );
    }

    /// @notice Bind a Circle Programmable Wallet to an agent. Called by the
    ///         registry operator after the wallet is provisioned off-chain.
    function bindWallet(bytes32 agentId, address wallet) external onlyOwner {
        Agent storage a = _agents[agentId];
        if (a.registeredAt == 0) revert UnknownAgent();
        if (a.wallet != address(0)) revert WalletAlreadyBound();
        a.wallet = wallet;
        emit WalletBound(agentId, wallet);
    }

    // ---------------------------------------------------------------------
    // views
    // ---------------------------------------------------------------------

    function getAgent(bytes32 agentId) external view returns (Agent memory) {
        Agent memory a = _agents[agentId];
        if (a.registeredAt == 0) revert UnknownAgent();
        return a;
    }

    function totalAgents() external view returns (uint256) {
        return allAgentIds.length;
    }

    /// @notice Pagination helper for the leaderboard.
    function listAgents(uint256 offset, uint256 limit)
        external
        view
        returns (Agent[] memory page)
    {
        uint256 n = allAgentIds.length;
        if (offset >= n) return new Agent[](0);
        uint256 end = offset + limit;
        if (end > n) end = n;
        page = new Agent[](end - offset);
        for (uint256 i = offset; i < end; i++) {
            page[i - offset] = _agents[allAgentIds[i]];
        }
    }

    // ---------------------------------------------------------------------
    // admin
    // ---------------------------------------------------------------------

    function setRegistrationFee(uint256 newFee) external onlyOwner {
        emit RegistrationFeeChanged(registrationFee, newFee);
        registrationFee = newFee;
    }

    function setFeeRecipient(address newRecipient) external onlyOwner {
        emit FeeRecipientChanged(feeRecipient, newRecipient);
        feeRecipient = newRecipient;
    }

    function topUpSponsoredQuota(uint256 extra) external onlyOwner {
        sponsoredQuota += extra;
    }
}
