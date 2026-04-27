from tests.snappi_tests.dataplane.imports import *  # noqa F403
from snappi_tests.dataplane.files.helper import *  # noqa F403
from tests.common.telemetry.metrics import GaugeMetric
from tests.snappi_tests.dataplane.test_packet_drop_threshold import boundary_check

from tests.common.telemetry.constants import (
    METRIC_LABEL_TG_FRAME_BYTES,
    METRIC_LABEL_TG_RFC2889_ENABLED,
)

logger = logging.getLogger(__name__)
pytestmark = [pytest.mark.topology("nut")]

test_results = pd.DataFrame(
    columns=[
        "Frame Ordering",
        "Frame Size",
        "Line Rate (%)",
        "Tx Frames",
        "Rx Frames",
        "Loss %",
        "Status",
        "Duration (s)",
    ]
)

ROUTE_RANGES = {"IPv6": [[["777:777:777::1", 64, 16]]], "IPv4": [[["100.1.1.1", 24, 16]]]}


@pytest.mark.parametrize("ip_version", ["IPv6"])
@pytest.mark.parametrize("rfc2889_enabled", [True, False])
def test_min_frame_size_no_loss(
    request,
    duthosts,
    snappi_api,  # noqa F811
    get_snappi_ports,
    fanout_graph_facts_multidut,  # noqa F811
    set_primary_chassis,
    create_snappi_config,
    rfc2889_enabled,
    ip_version,
    db_reporter,
):
    """
    Test to find the smallest frame size (at 100% line rate) that experiences no packet loss.
    """
    no_loss_min_frame = GaugeMetric("no_loss_min_frame", "No Loss Minimum Frame Size", "bytes", db_reporter)
    snappi_extra_params = SnappiTestParams()
    snappi_ports = get_duthost_interface_details(duthosts, get_snappi_ports, ip_version, protocol_type="bgp")
    port_distrbution = (slice(0, len(snappi_ports) // 2), slice(len(snappi_ports) // 2, None))
    tx_ports, rx_ports = snappi_ports[port_distrbution[0]], snappi_ports[port_distrbution[1]]
    ranges = ROUTE_RANGES[ip_version] * (len(snappi_ports))
    snappi_extra_params.protocol_config = {
        "Tx": {
            "route_ranges": ranges,
            "network_group": False,
            "protocol_type": "bgp",
            "ports": tx_ports,
            "subnet_type": ip_version,
            "is_rdma": False,
        },
        "Rx": {
            "route_ranges": ranges,
            "network_group": False,
            "protocol_type": "bgp",
            "ports": rx_ports,
            "subnet_type": ip_version,
            "is_rdma": False,
        },
    }

    # Base SNAPI configuration
    snappi_config, snappi_obj_handles = create_snappi_config(snappi_extra_params)
    start_frame, end_frame = 64, 9216
    # frame_sizes = list(range(start_frame, end_frame, 64))  # Candidate frame sizes

    snappi_extra_params.traffic_flow_config = [
        {
            "line_rate": 100,
            "frame_size": start_frame,  # initial
            "is_rdma": False,
            "flow_name": "min_frame_size_no_loss",
            "tx_names": snappi_obj_handles["Tx"]["ip"] + snappi_obj_handles["Rx"]["ip"],
            "rx_names": snappi_obj_handles["Rx"]["ip"] + snappi_obj_handles["Tx"]["ip"],
            "mesh_type": "mesh",
        }
    ]

    snappi_config = create_traffic_items(snappi_config, snappi_extra_params)
    snappi_api.set_config(snappi_config)
    start_stop(snappi_api, operation="start", op_type="protocols")
    # ***************************************************************************
    # Using RestPy Code
    ixnet_traffic_params = {"BiDirectional": True, "SrcDestMesh": "fullMesh"}
    ixnet = snappi_api._ixnetwork
    ixnet.Traffic.TrafficItem.find().update(**ixnet_traffic_params)
    ixnet.Traffic.FrameOrderingMode = "RFC2889" if rfc2889_enabled else "none"
    start_stop(snappi_api, operation="start", op_type="traffic")
    start_stop(snappi_api, operation="stop", op_type="traffic")
    # ***************************************************************************

    req = snappi_api.config_update().flows
    req.property_names = [req.SIZE]
    update_flow = snappi_config.flows[0]
    req.flows.append(update_flow)

    low, high = start_frame, end_frame
    best_frame_size = 9216

    while low <= high:
        mid = ((low + high) // 2 // 64) * 64  # Round to nearest 64 bytes
        logger.info("=" * 50)
        logger.info(f"Testing Frame Size: {mid} bytes at 100% Line Rate")
        logger.info("=" * 50)

        update_flow.size.fixed = mid
        snappi_api.update_flows(req)
        if boundary_check(snappi_api, snappi_config, mid, 100, rfc2889_enabled):
            best_frame_size = mid
            high = mid - 64  # try smaller frame
        else:
            low = mid + 64  # need larger frame

    logger.info(
        f"Final Smallest Frame Size Without Loss for FrameOrderingMode: {rfc2889_enabled} is: {best_frame_size} bytes"
    )

    no_loss_min_frame.record(
        best_frame_size,
        {
            "tg.ip_version": ip_version,
            METRIC_LABEL_TG_FRAME_BYTES: best_frame_size,
            METRIC_LABEL_TG_RFC2889_ENABLED: rfc2889_enabled,
        },
    )

    db_reporter.report()
    for ordering_mode, group in test_results.groupby("Frame Ordering"):
        summary = f"""
        Summary for Frame Ordering Mode: {ordering_mode}
        {"=" * 100}
        {tabulate(group, headers="keys", tablefmt="psql", showindex=False)}
        {"=" * 100}
        """
        logger.info(summary.strip())
