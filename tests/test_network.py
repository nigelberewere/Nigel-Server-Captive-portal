import sys
from unittest.mock import Mock, patch

sys.path.insert(0, 'backend')
import network


def test_mac_and_ip_validation():
    assert network._valid_mac('AA:BB:CC:DD:EE:FF') == 'aa:bb:cc:dd:ee:ff'
    assert network._valid_mac('bad;command') is None
    assert network._valid_ip('10.0.0.1') == '10.0.0.1'
    assert network._valid_ip('10.0.0.1;id') is None


def test_hotspot_guard_requires_ap_and_configured_address(monkeypatch):
    monkeypatch.setattr(network, 'WIFI_IFACE', 'wlp1s0')
    monkeypatch.setattr(network, 'WIFI_IP', '10.0.0.1')
    monkeypatch.setattr(network, 'WIFI_PREFIX', '24')
    monkeypatch.setattr(network, 'run_cmd', Mock(side_effect=[
        'Interface wlp1s0\n\ttype managed',
        '3: wlp1s0    inet 10.0.0.1/24',
    ]))
    assert not network._hotspot_active()


def test_nat_authenticated_path_returns():
    commands = []
    with patch.object(network, '_iptables') as iptables, patch.object(network, '_chain_exists', return_value=True), patch.object(network, '_rule_exists', return_value=True), patch.object(network, '_restore') as restore:
        with patch.object(network, 'WIFI_IFACE', 'wlp1s0'), patch.object(network, 'WIFI_IP', '10.0.0.1'), patch.object(network, 'WIFI_SUBNET', '10.0.0.0/24'), patch.object(network, '_hotspot_active', return_value=True), patch.object(network, '_default_route_iface', return_value=None):
            network._configure_chains()
    nat_rules = restore.call_args_list[0].args[2]
    assert any('-j RETURN' in rule for rule in nat_rules)
    assert not any('-j ACCEPT' in rule for rule in nat_rules)
