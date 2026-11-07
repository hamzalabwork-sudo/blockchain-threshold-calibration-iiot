// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title ThresholdRegistry: ledger governance of a gateway's calibrated authorization thresholds.
/// @notice A site operator proposes the two CUSUM thresholds calibrated on the site's benign
/// recording; an auditor (a different account) approves them. The contract enforces, at write
/// time, that (i) the calibration is for the model currently deployed, (ii) both thresholds are at
/// least the single-event floor, and (iii) proposer and approver differ. A calibration is valid
/// only while its model is current, so publishing a new model invalidates every gateway's
/// thresholds at once. Gateways read their thresholds from here and file recalibration requests
/// when their dependence monitor fires. Thresholds and dependence values are fixed point, x 1e4.
contract ThresholdRegistry {
    struct Calibration {
        bytes32 model;        // hash of the deployed detector and evidence table
        uint32 h1;            // CUSUM threshold, x 1e4
        uint32 h2;            // rho-mixture CUSUM threshold, x 1e4
        uint32 depCal;        // dependence statistic of the recording, x 1e4
        uint32 depBound;      // monitor bound: request recalibration above this, x 1e4
        bytes32 recording;    // hash of the recorded benign rows and the calibration seed
        bytes32 params;       // hash of (T, beta, N, B, q, rho0, floor)
        address proposer;
        address approver;
        uint64 approvedAt;
        bool recalRequested;
    }

    address public immutable owner;     // federation coordinator: publishes models, registers roles
    uint32 public immutable floor1;     // single-event floor of the CUSUM, x 1e4
    uint32 public immutable floor2;     // single-event floor of the mixture CUSUM, x 1e4
    bytes32 public currentModel;
    uint64 public modelEpoch;

    mapping(address => bool) public isOperator;
    mapping(address => bool) public isAuditor;
    mapping(uint32 => address) public gatewayOf;
    mapping(bytes32 => Calibration) public pending;   // proposal id -> proposal
    mapping(bytes32 => uint32) public pendingGateway;
    mapping(uint32 => Calibration) public active;     // gateway id -> approved calibration

    event ModelPublished(bytes32 indexed model, uint64 epoch);
    event CalibrationProposed(bytes32 indexed id, uint32 indexed gateway, bytes32 model, uint32 h1, uint32 h2,
                              bytes32 recording, address proposer);
    event CalibrationActivated(bytes32 indexed id, uint32 indexed gateway, address approver);
    event RecalibrationRequested(uint32 indexed gateway, uint32 depLive, uint32 depBound);

    modifier only(bool ok, string memory why) {
        require(ok, why);
        _;
    }

    constructor(uint32 _floor1, uint32 _floor2) {
        owner = msg.sender;
        floor1 = _floor1;
        floor2 = _floor2;
    }

    function setRoles(address who, bool operator_, bool auditor_) external only(msg.sender == owner, "owner") {
        isOperator[who] = operator_;
        isAuditor[who] = auditor_;
    }

    function setGateway(uint32 gw, address who) external only(msg.sender == owner, "owner") {
        gatewayOf[gw] = who;
    }

    function publishModel(bytes32 model) external only(msg.sender == owner, "owner") {
        currentModel = model;
        modelEpoch += 1;
        emit ModelPublished(model, modelEpoch);
    }

    function propose(uint32 gw, bytes32 model, uint32 h1, uint32 h2, uint32 depCal, uint32 depBound,
                     bytes32 recording, bytes32 params)
        external only(isOperator[msg.sender], "operator") returns (bytes32 id)
    {
        require(model == currentModel && model != bytes32(0), "stale model");
        require(h1 >= floor1 && h2 >= floor2, "below floor");
        require(depBound >= depCal, "bound");
        id = keccak256(abi.encode(gw, model, h1, h2, depCal, depBound, recording, params, msg.sender, block.number));
        pending[id] = Calibration(model, h1, h2, depCal, depBound, recording, params, msg.sender, address(0), 0, false);
        pendingGateway[id] = gw;
        emit CalibrationProposed(id, gw, model, h1, h2, recording, msg.sender);
    }

    function approve(bytes32 id) external only(isAuditor[msg.sender], "auditor") {
        Calibration memory c = pending[id];
        require(c.proposer != address(0), "unknown");
        require(c.proposer != msg.sender, "two-person rule");
        require(c.model == currentModel, "stale model");
        c.approver = msg.sender;
        c.approvedAt = uint64(block.timestamp);
        uint32 gw = pendingGateway[id];
        active[gw] = c;
        delete pending[id];
        delete pendingGateway[id];
        emit CalibrationActivated(id, gw, msg.sender);
    }

    function requestRecalibration(uint32 gw, uint32 depLive) external only(msg.sender == gatewayOf[gw], "gateway") {
        Calibration storage c = active[gw];
        require(depLive > c.depBound, "within bound");
        c.recalRequested = true;
        emit RecalibrationRequested(gw, depLive, c.depBound);
    }

    /// @notice The thresholds a gateway must run with; valid is false if none is approved for the
    /// current model or a recalibration is pending (the gateway then falls back to the bound).
    function thresholds(uint32 gw) external view returns (bool valid, uint32 h1, uint32 h2, uint32 depBound) {
        Calibration memory c = active[gw];
        valid = c.approver != address(0) && c.model == currentModel && !c.recalRequested;
        return (valid, c.h1, c.h2, c.depBound);
    }
}
