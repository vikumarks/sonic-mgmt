import snappi
from rich import print as pr
api = snappi.api(location='https://10.36.74.213:443', ext='ixnetwork')
config = api.config()
snappi_ports = ['10.36.74.213/1','10.36.74.213/2','10.36.74.213/3','10.36.74.213/4','10.36.74.213/5','10.36.74.213/6','10.36.74.213/7','10.36.74.213/8']
for i in range(len(snappi_ports)):
    config.ports.port(name='Port {}'.format(i),location=snappi_ports[i])
    port_speed = 800000

speed_gbps = int(port_speed/1000)
config.options.port_options.location_preemption = True
l1_config = config.layer1.layer1()[-1]
l1_config.name = 'L1 config'
l1_config.port_names = [port.name for port in config.ports]
l1_config.speed = 'speed_{}_gbps'.format(speed_gbps)
l1_config.ieee_media_defaults = False
l1_config.auto_negotiate = False
l1_config.auto_negotiation.link_training = False
l1_config.auto_negotiation.rs_fec = True

pfc = l1_config.flow_control.ieee_802_1qbb
pfc.pfc_delay = 0
api.set_config(config)
import pdb;pdb.set_trace()