import subprocess
import logging
import os

logger = logging.getLogger(__name__)

IPSET_MAC_NAME = "nigel_auth_macs"
IPSET_IP_NAME = "nigel_auth_ips"
WIFI_IFACE = "wlan0"  # Will be updated by setup.sh if different

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.warning(f"Command failed: {cmd}, error: {e.stderr.strip()}")
        return None

def get_mac_from_ip(ip_address):
    """
    Look up the MAC address of a client IP on the local subnet.
    Checks /proc/net/arp, dnsmasq leases, and `ip neigh`.
    """
    if not ip_address:
        return None
    if ip_address in ('127.0.0.1', '::1'):
        return '00:00:00:00:00:01'

    # 1. Check /proc/net/arp
    try:
        if os.path.exists('/proc/net/arp'):
            with open('/proc/net/arp', 'r') as f:
                for line in f.readlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4 and parts[0] == ip_address:
                        mac = parts[3].strip().lower()
                        if mac and mac != '00:00:00:00:00:00':
                            return mac
    except Exception as e:
        logger.warning(f"Error reading /proc/net/arp: {e}")

    # 2. Check dnsmasq.leases
    for lease_path in ['/var/lib/misc/dnsmasq.leases', '/var/lib/dnsmasq/dnsmasq.leases', '/tmp/dnsmasq.leases']:
        try:
            if os.path.exists(lease_path):
                with open(lease_path, 'r') as f:
                    for line in f:
                        parts = line.split()
                        if len(parts) >= 3 and parts[2] == ip_address:
                            mac = parts[1].strip().lower()
                            if mac and mac != '00:00:00:00:00:00':
                                return mac
        except Exception:
            pass

    # 3. Fallback to `ip neigh show`
    try:
        out = run_cmd(f"ip neigh show {ip_address}")
        if out:
            parts = out.split()
            if "lladdr" in parts:
                idx = parts.index("lladdr") + 1
                if idx < len(parts):
                    return parts[idx].strip().lower()
    except Exception as e:
        logger.warning(f"Error checking ip neigh: {e}")

    return None

def init_ipset():
    """Create the MAC and IP ipsets if they do not exist."""
    run_cmd(f"sudo ipset create {IPSET_MAC_NAME} hash:mac -exist")
    run_cmd(f"sudo ipset create {IPSET_IP_NAME} hash:ip -exist")

def add_device_to_ipset(mac_address=None, ip_address=None):
    """Add an authenticated MAC and/or IP address to the ipset."""
    if mac_address and ':' in mac_address and len(mac_address) == 17:
        run_cmd(f"sudo ipset add {IPSET_MAC_NAME} {mac_address} -exist")
    if ip_address and ip_address not in ('127.0.0.1', '::1', 'localhost'):
        run_cmd(f"sudo ipset add {IPSET_IP_NAME} {ip_address} -exist")

def remove_device_from_ipset(mac_address=None, ip_address=None):
    """Remove a MAC and/or IP address from the ipset."""
    if mac_address and ':' in mac_address:
        run_cmd(f"sudo ipset del {IPSET_MAC_NAME} {mac_address} -exist")
    if ip_address and ip_address not in ('127.0.0.1', '::1', 'localhost'):
        run_cmd(f"sudo ipset del {IPSET_IP_NAME} {ip_address} -exist")

def flush_ipset():
    """Clear all authenticated MACs and IPs."""
    run_cmd(f"sudo ipset flush {IPSET_MAC_NAME}")
    run_cmd(f"sudo ipset flush {IPSET_IP_NAME}")

def apply_iptables_rules():
    """
    Set up iptables to allow authenticated devices while redirecting
    unauthenticated traffic to the captive portal.
    """
    init_ipset()

    # Enable IP forwarding in the kernel for internet routing
    run_cmd("sudo sysctl -w net.ipv4.ip_forward=1")

    # 1. DNS queries (Port 53) are always allowed
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -p udp --dport 53 -j ACCEPT 2>/dev/null || sudo iptables -t nat -I PREROUTING 1 -i {WIFI_IFACE} -p udp --dport 53 -j ACCEPT")
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -p tcp --dport 53 -j ACCEPT 2>/dev/null || sudo iptables -t nat -I PREROUTING 2 -i {WIFI_IFACE} -p tcp --dport 53 -j ACCEPT")

    # 2. Port 5000 direct access
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -p tcp --dport 5000 -j ACCEPT 2>/dev/null || sudo iptables -t nat -I PREROUTING 3 -i {WIFI_IFACE} -p tcp --dport 5000 -j ACCEPT")

    # 3. Always redirect local port 80 traffic (destined for 10.0.0.1) to port 5000 so OS probes reach Flask
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -p tcp -d 10.0.0.1 --dport 80 -j REDIRECT --to-port 5000 2>/dev/null || sudo iptables -t nat -I PREROUTING 4 -i {WIFI_IFACE} -p tcp -d 10.0.0.1 --dport 80 -j REDIRECT --to-port 5000")

    # 4. For authenticated MACs & IPs: allow all external traffic
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -m set --match-set {IPSET_MAC_NAME} src -j ACCEPT 2>/dev/null || sudo iptables -t nat -I PREROUTING 5 -i {WIFI_IFACE} -m set --match-set {IPSET_MAC_NAME} src -j ACCEPT")
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -m set --match-set {IPSET_IP_NAME} src -j ACCEPT 2>/dev/null || sudo iptables -t nat -I PREROUTING 6 -i {WIFI_IFACE} -m set --match-set {IPSET_IP_NAME} src -j ACCEPT")

    # 5. Redirect unauthenticated external HTTP (Port 80) to captive portal
    run_cmd(f"sudo iptables -t nat -C PREROUTING -i {WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 5000 2>/dev/null || sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 5000")

    # 5. FORWARD rules: Allow authenticated devices to forward packets through router to WAN
    run_cmd(f"sudo iptables -C FORWARD -m set --match-set {IPSET_MAC_NAME} src -j ACCEPT 2>/dev/null || sudo iptables -I FORWARD 1 -m set --match-set {IPSET_MAC_NAME} src -j ACCEPT")
    run_cmd(f"sudo iptables -C FORWARD -m set --match-set {IPSET_IP_NAME} src -j ACCEPT 2>/dev/null || sudo iptables -I FORWARD 2 -m set --match-set {IPSET_IP_NAME} src -j ACCEPT")
    run_cmd(f"sudo iptables -C FORWARD -m state --state RELATED,ESTABLISHED -j ACCEPT 2>/dev/null || sudo iptables -I FORWARD 3 -m state --state RELATED,ESTABLISHED -j ACCEPT")

    # 6. MASQUERADE outgoing traffic to WAN interfaces (non-wlan)
    run_cmd(f"sudo iptables -t nat -C POSTROUTING -o ! {WIFI_IFACE} -j MASQUERADE 2>/dev/null || sudo iptables -t nat -A POSTROUTING -o ! {WIFI_IFACE} -j MASQUERADE")

def restart_dnsmasq():
    """Restart dnsmasq to apply any config changes."""
    run_cmd("sudo systemctl restart dnsmasq")

