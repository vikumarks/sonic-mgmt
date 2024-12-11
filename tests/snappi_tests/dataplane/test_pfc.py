from tests.snappi_tests.dataplane.imports import *

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.topology('tgen')]


dut_port_config = []
PAUSE_FLOW_NAME = 'Pause Storm'
TEST_FLOW_NAME = 'Test Flow'
TEST_FLOW_AGGR_RATE_PERCENT = 45
BG_FLOW_NAME = 'Background Flow'
BG_FLOW_AGGR_RATE_PERCENT = 45
data_flow_pkt_size = 1024
DATA_FLOW_DURATION_SEC = 15
data_flow_delay_sec = 1
SNAPPI_POLL_DELAY_SEC = 2
PAUSE_FLOW_DUR_BASE_SEC = data_flow_delay_sec + DATA_FLOW_DURATION_SEC
TOLERANCE_THRESHOLD = 0.05
CONTINUOUS_MODE = -5
ANSIBLE_POLL_DELAY_SEC = 4



SNAPPI_POLL_DELAY_SEC = 2
CONTINUOUS_MODE = -5
ANSIBLE_POLL_DELAY_SEC = 4

def run_traffic(duthost,
                api,
                config,
                data_flow_names,
                all_flow_names,
                exp_dur_sec,
                snappi_extra_params):

    """
    Run traffic and return per-flow statistics, and capture packets if needed.
    Args:
        duthost (obj): DUT host object
        api (obj): snappi session
        config (obj): experiment config (testbed config + flow config)
        data_flow_names (list): list of names of data (test and background) flows
        all_flow_names (list): list of names of all the flows
        exp_dur_sec (int): experiment duration in second
        snappi_extra_params (SnappiTestParams obj): additional parameters for Snappi traffic
    Returns:
        flow_metrics (snappi metrics object): per-flow statistics from TGEN (right after flows end)
        switch_device_results (dict): statistics from DUT on both TX and RX and per priority
        in_flight_flow_metrics (snappi metrics object): in-flight statistics per flow from TGEN
                                                        (right before flows end)
    """

    api.set_config(config)
    logger.info("Wait for Arp to Resolve ...")
    wait_for_arp(api, max_attempts=30, poll_interval_sec=2)
    pcap_type = snappi_extra_params.packet_capture_type
    base_flow_config = snappi_extra_params.base_flow_config
    switch_tx_lossless_prios = sum(base_flow_config["dut_port_config"][1].values(), [])
    switch_rx_port = snappi_extra_params.base_flow_config["tx_port_config"].peer_port
    switch_tx_port = snappi_extra_params.base_flow_config["rx_port_config"].peer_port
    switch_device_results = None
    in_flight_flow_metrics = None

    if pcap_type != packet_capture.NO_CAPTURE:
        logger.info("Starting packet capture ...")
        cs = api.control_state()
        cs.port.capture.port_names = snappi_extra_params.packet_capture_ports
        cs.port.capture.state = cs.port.capture.START
        api.set_control_state(cs)

    duthost.command("sonic-clear counters \n")

    duthost.command("sonic-clear queuecounters \n")

    logger.info("Starting transmit on all flows ...")
    cs = api.control_state()
    cs.traffic.flow_transmit.state = cs.traffic.flow_transmit.START
    api.set_control_state(cs)


    # Test needs to run for at least 10 seconds to allow successive device polling
    if snappi_extra_params.poll_device_runtime and exp_dur_sec > 10:
        logger.info("Polling DUT for traffic statistics for {} seconds ...".format(exp_dur_sec))
        switch_device_results = {}
        switch_device_results["tx_frames"] = {}
        switch_device_results["rx_frames"] = {}
        for lossless_prio in switch_tx_lossless_prios:
            switch_device_results["tx_frames"][lossless_prio] = []
            switch_device_results["rx_frames"][lossless_prio] = []
        exp_dur_sec = exp_dur_sec + ANSIBLE_POLL_DELAY_SEC  # extra time to allow for device polling
        poll_freq_sec = int(exp_dur_sec / 10)

        for poll_iter in range(10):
            for lossless_prio in switch_tx_lossless_prios:
                switch_device_results["tx_frames"][lossless_prio].append(get_egress_queue_count(duthost, switch_tx_port,
                                                                                                lossless_prio)[0])
                switch_device_results["rx_frames"][lossless_prio].append(get_egress_queue_count(duthost, switch_rx_port,
                                                                                                lossless_prio)[0])
            time.sleep(poll_freq_sec)

            if poll_iter == 5:
                logger.info("Polling TGEN for in-flight traffic statistics...")
                in_flight_flow_metrics = fetch_snappi_flow_metrics(api, all_flow_names)
                flow_names = [metric.name for metric in in_flight_flow_metrics if metric.name in data_flow_names]
                tx_frames = [metric.frames_tx for metric in in_flight_flow_metrics if metric.name in data_flow_names]
                rx_frames = [metric.frames_rx for metric in in_flight_flow_metrics if metric.name in data_flow_names]
                logger.info("In-flight traffic statistics for flows: {}".format(flow_names))
                logger.info("In-flight TX frames: {}".format(tx_frames))
                logger.info("In-flight RX frames: {}".format(rx_frames))
        logger.info("DUT polling complete")
    else:
        time.sleep(exp_dur_sec*(2/5))  # no switch polling required, only TGEN polling
        logger.info("Polling TGEN for in-flight traffic statistics...")
        in_flight_flow_metrics = fetch_snappi_flow_metrics(api, all_flow_names)  # fetch in-flight metrics from TGEN
        time.sleep(exp_dur_sec*(3/5))

    attempts = 0
    max_attempts = 20

    while attempts < max_attempts:
        logger.info("Checking if all flows have stopped. Attempt #{}".format(attempts + 1))
        flow_metrics = fetch_snappi_flow_metrics(api, data_flow_names)

        # If all the data flows have stopped
        transmit_states = [metric.transmit for metric in flow_metrics]
        if len(flow_metrics) == len(data_flow_names) and\
           list(set(transmit_states)) == ['stopped']:
            logger.info("All test and background traffic flows stopped")
            time.sleep(SNAPPI_POLL_DELAY_SEC)
            break
        else:
            time.sleep(1)
            attempts += 1

    pytest_assert(attempts < max_attempts,"Flows do not stop in {} seconds".format(max_attempts))

    if pcap_type != packet_capture.NO_CAPTURE:
        logger.info("Stopping packet capture ...")
        request = api.capture_request()
        request.port_name = snappi_extra_params.packet_capture_ports[0]
        cs = api.control_state()
        cs.port.capture.state = cs.port.capture.STOP
        api.set_control_state(cs)

        logger.info("Retrieving and saving packet capture to {}.pcapng".format(snappi_extra_params.packet_capture_file))
        pcap_bytes = api.get_capture(request)
        with open(snappi_extra_params.packet_capture_file + ".pcapng", 'wb') as fid:
            fid.write(pcap_bytes.getvalue())

    # Dump per-flow statistics
    logger.info("Dumping per-flow statistics")
    flow_metrics = fetch_snappi_flow_metrics(api, all_flow_names)
    logger.info("Stopping transmit on all remaining flows")

    cs = api.control_state()
    cs.traffic.flow_transmit.state = cs.traffic.flow_transmit.STOP
    api.set_control_state(cs)

    return flow_metrics, switch_device_results, in_flight_flow_metrics

def test_pfc(snappi_api,                  # noqa F811
            snappi_testbed_config,       # noqa F811
            conn_graph_facts,            # noqa F811
            fanout_graph_facts,          # noqa F811
            duthosts,
            rand_one_dut_hostname,
            rand_one_dut_portname_oper_up,
            lossless_prio_list,          # noqa F811
            lossy_prio_list,
            all_prio_list,             # noqa F811
            prio_dscp_map):              # noqa F811
    """
    Test if PFC can pause multiple lossless priorities

    Args:
        snappi_api (pytest fixture): SNAPPI session
        snappi_testbed_config (pytest fixture): testbed configuration information
        conn_graph_facts (pytest fixture): connection graph
        fanout_graph_facts (pytest fixture): fanout graph
        duthosts (pytest fixture): list of DUTs
        rand_one_dut_hostname (str): hostname of DUT
        rand_one_dut_portname_oper_up (str): port to test, e.g., 's6100-1|Ethernet0'
        lossless_prio_list (pytest fixture): list of all the lossless priorities
        lossy_prio_list (pytest fixture): list of all the lossy priorities
        prio_dscp_map (pytest fixture): priority vs. DSCP map (key = priority).

    Returns:
        N/A
    """

    dut_hostname, dut_port = rand_one_dut_portname_oper_up.split('|')
    pytest_require(rand_one_dut_hostname == dut_hostname,
                   "Port is not mapped to the expected DUT")

    testbed_config, port_config_list = snappi_testbed_config
    duthost = duthosts[rand_one_dut_hostname]
    test_prio_list = lossless_prio_list
    bg_prio_list = lossy_prio_list
    api=snappi_api
    conn_data=conn_graph_facts
    fanout_data=fanout_graph_facts
    pause_prio_list=all_prio_list
    test_traffic_pause=True
    snappi_extra_params=None                
    global_pause=False


    pytest_assert(testbed_config is not None, 'Fail to get L2/3 testbed config')

    if snappi_extra_params is None:
        snappi_extra_params = SnappiTestParams()

    stop_pfcwd(duthost)
    disable_packet_aging(duthost)
    global DATA_FLOW_DURATION_SEC
    global data_flow_delay_sec

    # Get the ID of the port to test
    port_id = get_dut_port_id(dut_hostname=duthost.hostname,
                              dut_port=dut_port,
                              conn_data=conn_data,
                              fanout_data=fanout_data)

    pytest_assert(port_id is not None,'Fail to get ID for port {}'.format(dut_port))

    # Single linecard and hence rx_dut and tx_dut are the same.
    # rx_dut and tx_dut are used to verify_pause_frame_count
    rx_dut = duthost
    tx_dut = duthost

    # Rate percent must be an integer
    bg_flow_rate_percent = int(BG_FLOW_AGGR_RATE_PERCENT / len(bg_prio_list))
    test_flow_rate_percent = int(TEST_FLOW_AGGR_RATE_PERCENT / len(test_prio_list))

    # Generate base traffic config
    snappi_extra_params.base_flow_config = setup_base_traffic_config(testbed_config,port_config_list,port_id)


    if snappi_extra_params.headroom_test_params is not None:
        DATA_FLOW_DURATION_SEC += 10
        data_flow_delay_sec += 2

        # Set up pfc delay parameter
        l1_config = testbed_config.layer1[0]
        pfc = l1_config.flow_control.ieee_802_1qbb
        pfc.pfc_delay = snappi_extra_params.headroom_test_params[0]

    if snappi_extra_params.poll_device_runtime:
        # If the switch needs to be polled as traffic is running for stats,
        # then the test runtime needs to be increased for the polling delay
        DATA_FLOW_DURATION_SEC += ANSIBLE_POLL_DELAY_SEC
        data_flow_delay_sec = ANSIBLE_POLL_DELAY_SEC

    if snappi_extra_params.packet_capture_type != packet_capture.NO_CAPTURE:
        # Setup capture config
        if snappi_extra_params.is_snappi_ingress_port_cap:
            # packet capture is required on the ingress snappi port
            snappi_extra_params.packet_capture_ports = [snappi_extra_params.base_flow_config["rx_port_name"]]
        else:
            # packet capture will be on the egress snappi port
            snappi_extra_params.packet_capture_ports = [snappi_extra_params.base_flow_config["tx_port_name"]]

        snappi_extra_params.packet_capture_file = snappi_extra_params.packet_capture_type.value

        config_capture_pkt(testbed_config=testbed_config,
                           port_names=snappi_extra_params.packet_capture_ports,
                           capture_type=snappi_extra_params.packet_capture_type,
                           capture_name=snappi_extra_params.packet_capture_file)
        logger.info("Packet capture file: {}.pcapng".format(snappi_extra_params.packet_capture_file))

    # Set default traffic flow configs if not set
    if snappi_extra_params.traffic_flow_config.data_flow_config is None:
        snappi_extra_params.traffic_flow_config.data_flow_config = {
            "flow_name": TEST_FLOW_NAME,
            "flow_dur_sec": DATA_FLOW_DURATION_SEC,
            "flow_rate_percent": test_flow_rate_percent,
            "flow_rate_pps": None,
            "flow_rate_bps": None,
            "flow_pkt_size": data_flow_pkt_size,
            "flow_pkt_count": None,
            "flow_delay_sec": data_flow_delay_sec,
            "flow_traffic_type": traffic_flow_mode.FIXED_DURATION
        }

    if snappi_extra_params.traffic_flow_config.background_flow_config is None and \
       snappi_extra_params.gen_background_traffic:
        snappi_extra_params.traffic_flow_config.background_flow_config = {
            "flow_name": BG_FLOW_NAME,
            "flow_dur_sec": DATA_FLOW_DURATION_SEC,
            "flow_rate_percent": bg_flow_rate_percent,
            "flow_rate_pps": None,
            "flow_rate_bps": None,
            "flow_pkt_size": data_flow_pkt_size,
            "flow_pkt_count": None,
            "flow_delay_sec": data_flow_delay_sec,
            "flow_traffic_type": traffic_flow_mode.FIXED_DURATION
        }

    if snappi_extra_params.traffic_flow_config.pause_flow_config is None:
        snappi_extra_params.traffic_flow_config.pause_flow_config = {
            "flow_name": PAUSE_FLOW_NAME,
            "flow_dur_sec": None,
            "flow_rate_percent": None,
            "flow_rate_pps": calc_pfc_pause_flow_rate(int(testbed_config.layer1[0].speed.split('_')[1])),
            "flow_rate_bps": None,
            "flow_pkt_size": 64,
            "flow_pkt_count": None,
            "flow_delay_sec": 0,
            "flow_traffic_type": traffic_flow_mode.CONTINUOUS
        }

    # PFC pause frame capture is requested
    valid_pfc_frame_test = True if snappi_extra_params.packet_capture_type == packet_capture.PFC_CAPTURE else False
    if valid_pfc_frame_test:
        snappi_extra_params.traffic_flow_config.pause_flow_config["flow_dur_sec"] = DATA_FLOW_DURATION_SEC + \
            data_flow_delay_sec + SNAPPI_POLL_DELAY_SEC + PAUSE_FLOW_DUR_BASE_SEC
        snappi_extra_params.traffic_flow_config.pause_flow_config["flow_traffic_type"] = \
            traffic_flow_mode.FIXED_DURATION

    # Generate test flow config
    generate_test_flows(testbed_config=testbed_config,test_flow_prio_list=test_prio_list,prio_dscp_map=prio_dscp_map,snappi_extra_params=snappi_extra_params)
    # Generate pause storm config
    generate_pause_flows(testbed_config=testbed_config,pause_prio_list=pause_prio_list,global_pause=global_pause,snappi_extra_params=snappi_extra_params)
    if snappi_extra_params.gen_background_traffic:
        # Generate background flow config
        generate_background_flows(testbed_config=testbed_config,bg_flow_prio_list=bg_prio_list,prio_dscp_map=prio_dscp_map,snappi_extra_params=snappi_extra_params)


    flows = testbed_config.flows
    all_flow_names = [flow.name for flow in flows]
    data_flow_names = [flow.name for flow in flows if PAUSE_FLOW_NAME not in flow.name]

    # Clear PFC, queue and interface counters before traffic run
    duthost.command("pfcstat -c")
    time.sleep(1)
    duthost.command("sonic-clear queuecounters")
    time.sleep(1)
    duthost.command("sonic-clear counters")
    time.sleep(1)

    # Reset pfc delay parameter
    pfc = testbed_config.layer1[0].flow_control.ieee_802_1qbb
    pfc.pfc_delay = 0

    tgen_flow_stats, switch_flow_stats, in_flight_flow_metrics = run_traffic(duthost=duthost,api=api,config=testbed_config,data_flow_names=data_flow_names,all_flow_names=all_flow_names,exp_dur_sec=DATA_FLOW_DURATION_SEC + data_flow_delay_sec,snappi_extra_params=snappi_extra_params)

    # Verify PFC pause frames
    if valid_pfc_frame_test:
        is_valid_pfc_frame, error_msg = validate_pfc_frame(snappi_extra_params.packet_capture_file + ".pcapng")
        pytest_assert(is_valid_pfc_frame, error_msg)
        return

    speed_gbps = int(testbed_config.layer1[0].speed.split('_')[1])
    # Verify pause flows
    verify_pause_flow(flow_metrics=tgen_flow_stats,pause_flow_name=PAUSE_FLOW_NAME)

    if snappi_extra_params.gen_background_traffic:
        # Verify background flows
        verify_background_flow(flow_metrics=tgen_flow_stats,speed_gbps=speed_gbps,tolerance=TOLERANCE_THRESHOLD,snappi_extra_params=snappi_extra_params)
        #*** Failed: Background Flow Prio 1 should not have any dropped packet          XXXXXXXXXX

    # Verify basic test flows metrics from ixia
    verify_basic_test_flow(flow_metrics=tgen_flow_stats,speed_gbps=speed_gbps,tolerance=TOLERANCE_THRESHOLD,test_flow_pause=test_traffic_pause,snappi_extra_params=snappi_extra_params)

    # Verify PFC pause frame count on the DUT
    # rx_dut is Ingress DUT receiving traffic.
    # tx_dut is Egress DUT sending traffic to IXIA and also receiving PFCs.
    verify_pause_frame_count_dut(rx_dut=rx_dut,tx_dut=tx_dut,test_traffic_pause=test_traffic_pause,global_pause=global_pause,snappi_extra_params=snappi_extra_params)

    # Verify in flight TX lossless packets do not leave the DUT when traffic is expected
    # to be paused, or leave the DUT when the traffic is not expected to be paused
    verify_egress_queue_frame_count(duthost=duthost,switch_flow_stats=switch_flow_stats,test_traffic_pause=test_traffic_pause,snappi_extra_params=snappi_extra_params)

    if test_traffic_pause and not snappi_extra_params.gen_background_traffic:
        # Verify TX frame count on the DUT when traffic is expected to be paused
        # and only test traffic flows are generated
        verify_tx_frame_count_dut(duthost=duthost,api=api,snappi_extra_params=snappi_extra_params)
        # ** Failed: Additional frames are transmitted outside of deviation. Possible PFC frames are counted.             XXXXXXXXXXXXXXX
        # Verify TX frame count on the DUT when traffic is expected to be paused
        # and only test traffic flows are generated
        verify_rx_frame_count_dut(duthost=duthost,api=api,snappi_extra_params=snappi_extra_params)
        # *** ZeroDivisionError: division by zero                                      XXXXXXXXXXXXXXXXXXXX
    '''
    if test_traffic_pause:
        # Verify in flight TX packets count relative to switch buffer size
        verify_in_flight_buffer_pkts(duthost=duthost,flow_metrics=in_flight_flow_metrics,snappi_extra_params=snappi_extra_params)
        # *** Failed: Total TX bytes 24205312 should be smaller than DUT buffer size 14628114          XXXXXXXXXXXXXXXXXXXX
    else:
        # Verify zero pause frames are counted when the PFC class enable vector is not set
        verify_unset_cev_pause_frame_count(duthost=duthost,snappi_extra_params=snappi_extra_params)
    '''