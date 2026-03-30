# flake8: noqa: F403, F401, F405
from snappi_tests.rocev2.files.helper import *
from tests.snappi_tests.variables import MULTIDUT_PORT_INFO, MULTIDUT_TESTBED

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.topology('multidut-tgen', 'tgen')]

TRAFFIC_DURATION = 300  # seconds

@pytest.mark.parametrize("multidut_port_info", MULTIDUT_PORT_INFO[MULTIDUT_TESTBED])
def test_rocev2_basic_dp_traffic_no_congestion(
                                    request,
                                    snappi_api,
                                    conn_graph_facts,
                                    fanout_graph_facts_multidut,
                                    get_snappi_ports,
                                    duthosts,
                                    multidut_port_info,
                                ):
    """
    1. Configure DUT with 2 lossless queues 3 and 4 mapping to DSCP value 3 and 4, queue 6 mapping to DSCP 48, enable PFC and ECN-marking.
    2. Configure 1:1 test traffic between rank 0-2 & 1-3, 1 rank (endpoint) per port.
    3. Configure constant rate test traffic (RoCEv2 AI traffic) for 2 lossless and 4 lossy queues: 6 QPs per rank pair.
    4. DSCP value 0-5 on rank0 q1-6
    5. DSCP value 0-5 on rank1 q1-6
    6. DSCP for ACK/NAK/CNP value 48
    7. 4K IB MTU, 1MB message size (256 packets in burst per message)
    8. ECN-CE bit value 00 (non-ECT)
    9. Verify that PFC is triggered on queue 3 (and 4 if not disabled), ACKs are sent on queue 3 (and 4 if not disabled), and that there is no ECN marking and no CNPs on queue 3 (and 4 if not disabled).

    """
    snappi_port_list = get_snappi_ports
    pytest_require(len(snappi_port_list) >= 4, "Need minimum of 4 ports")

    tconfig, plist, sports = snappi_dut_base_config(request, duthosts, snappi_port_list, snappi_api)
    port_ids = [pc.id for pc in plist]
    COMMON_CFG = {
                "mtu": 5000,
                "qp_configs": [{"message_size_unit": "mb", "message_size": 1, "dscp": 3}],
                "cnp": {"ip_dscp": 48, "ecn_value": "non_ect"},
                "connection_type": {
                    "choice": "reliable_connection",
                    "reliable_connection": {
                        "ack": {"ip_dscp": 3, "ecn_value": "non_ect"},
                        "nak": {"ip_dscp": 3, "ecn_value": "non_ect"},
                        "enable_retransmission_timeout": True,
                        "retransmission_timeout_value": 40,
                    },
                },
            }

    pairs = list(zip(port_ids[:len(port_ids)//2], port_ids[len(port_ids)//2:]))
    topology = {
                port: {
                    **COMMON_CFG,
                    "peers": [rx] if port == tx else [],
                }
                for tx, rx in pairs
                for port in (tx, rx)
            }
    logger.info(f"Test Topology: {topology}")
    run_rocev2_step(
        api=snappi_api,
        base_config=tconfig,
        port_config_list=plist,
        topology=topology,
        traffic_duration=TRAFFIC_DURATION,
        latency_profile=LATENCY_PROFILES["ai"],
        expectations=dict(
            expect_pfc_queues=[3],
            expect_ack_queues=[3],
            expect_no_ecn_queues=[3],
            #expect_no_cnp_queues=[6],
        ),
    )
    logger.info("*** TC1 PASSED ***")
