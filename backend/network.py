import subprocess
import logging

logger = logging.getLogger(__name__)

IPSET_NAME = "nigel_auth_macs"
WIFI_IFACE = "wlan0"  # Could be pulled from DB settings

def run_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        logger.error(f"Command failed: {cmd}")
        logger.error(f"Error: {e.stderr}")
        return None

def init_ipset():
    """Create the ipset if it doesn't exist."""
    run_cmd(f"sudo ipset create {IPSET_NAME} hash:mac -exist")

def add_device_to_ipset(mac_address):
    """Add an authenticated MAC address to the ipset."""
    run_cmd(f"sudo ipset add {IPSET_NAME} {mac_address} -exist")

def remove_device_from_ipset(mac_address):
    """Remove a MAC address from the ipset."""
    run_cmd(f"sudo ipset del {IPSET_NAME} {mac_address} -exist")

def flush_ipset():
    """Clear all authenticated MACs."""
    run_cmd(f"sudo ipset flush {IPSET_NAME}")

def apply_iptables_rules():
    """
    Set up iptables to route unauthenticated traffic to the captive portal.
    Assuming the portal runs on port 5000 and dnsmasq on port 53.
    """
    # Flush existing nat PREROUTING to avoid duplicates (simplified for this script)
    # run_cmd("sudo iptables -t nat -F PREROUTING")
    
    # Allow DNS
    run_cmd(f"sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -p udp --dport 53 -j ACCEPT")
    run_cmd(f"sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -p tcp --dport 53 -j ACCEPT")
    
    # Allow traffic from authenticated MACs
    run_cmd(f"sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -m set --match-set {IPSET_NAME} src -j ACCEPT")
    
    # Redirect HTTP to local portal
    run_cmd(f"sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -p tcp --dport 80 -j REDIRECT --to-port 5000")
    
    # Redirect HTTPS to local portal (requires SSL setup for the portal to avoid cert errors, or simply reject)
    run_cmd(f"sudo iptables -t nat -A PREROUTING -i {WIFI_IFACE} -p tcp --dport 443 -j REDIRECT --to-port 5000")

def restart_dnsmasq():
    """Restart dnsmasq to apply any config changes."""
    run_cmd("sudo systemctl restart dnsmasq")
