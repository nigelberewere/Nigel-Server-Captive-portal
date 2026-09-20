import ipaddress
import logging
import os
import re
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

IPSET_MAC_NAME = "nigel_auth_macs"
IPSET_TRUSTED_NAME = "nigel_trusted_macs"
WIFI_IFACE = os.environ.get("WIFI_IFACE")
WIFI_IP = os.environ.get("NIGEL_WIFI_IP")
WIFI_PREFIX = os.environ.get("NIGEL_WIFI_PREFIX", "24")
WIFI_SUBNET = os.environ.get("NIGEL_WIFI_SUBNET")
STRICT_MODE = os.environ.get("NIGEL_STRICT", "1").lower() not in {"0", "false", "no"}
MAC_RE = re.compile(r"^[0-9a-f]{2}(?::[0-9a-f]{2}){5}$", re.IGNORECASE)
IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
CHAINS = (
    ("nat", "NIGEL_NAT", "PREROUTING"),
    ("filter", "NIGEL_INPUT", "INPUT"),
    ("filter", "NIGEL_FWD", "FORWARD"),
    ("filter", "NIGEL_DOCKER_USER", "DOCKER-USER"),
)
_watchdog_started = False


def _valid_mac(value):
    return value.lower() if isinstance(value, str) and MAC_RE.fullmatch(value) else None


def _valid_ip(value):
    try:
        return str(ipaddress.ip_address(value))
    except (ValueError, TypeError):
        return None


def _valid_iface(value):
    if not isinstance(value, str) or not IFACE_RE.fullmatch(value):
        raise ValueError("WIFI_IFACE is not configured or is invalid")
    return value


def _configured_ip():
    value = _valid_ip(WIFI_IP)
    if not value:
        raise ValueError("NIGEL_WIFI_IP is not configured or is invalid")
    return value


def _hotspot_active():
    if not WIFI_IFACE or not WIFI_IP:
        return False
    mode = run_cmd(["iw", "dev", WIFI_IFACE, "info"])
    address = run_cmd(["ip", "-4", "-o", "addr", "show", "dev", WIFI_IFACE])
    return bool(mode and "type AP" in mode and address and f"{WIFI_IP}/{WIFI_PREFIX}" in address)


def run_cmd(args, check=False, input_text=None):
    if not isinstance(args, (list, tuple)) or not args:
        raise ValueError("command must be a non-empty argument list")
    try:
        result = subprocess.run(
            list(args), check=check, input=input_text, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True
        )
        if result.returncode and check:
            logger.warning("Command failed: %s: %s", args, result.stderr.strip())
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        logger.warning("Command failed: %s: %s", args, exc)
        if check:
            raise
        return None


def _iptables(table, *args, check=False):
    command = ["iptables", "-w"]
    if table:
        command += ["-t", table]
    return run_cmd(command + list(args), check=check)


def _rule_exists(table, chain, *rule):
    command = ["iptables", "-w"]
    if table:
        command += ["-t", table]
    result = subprocess.run(command + ["-C", chain, *rule], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode == 0


def _chain_exists(table, chain):
    command = ["iptables", "-w"]
    if table:
        command += ["-t", table]
    result = subprocess.run(command + ["-L", chain], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return result.returncode == 0


def _chain_has_rules(table, chain):
    command = ["iptables-save", "-t", table]
    saved = run_cmd(command) or ''
    return any(line.startswith(f"-A {chain} ") for line in saved.splitlines())


def _ensure_chain(table, chain, parent):
    if not _chain_exists(table, chain):
        _iptables(table, "-N", chain, check=True)
    if not _rule_exists(table, parent, "-j", chain):
        _iptables(table, "-I", parent, "1", "-j", chain, check=True)


def _restore(table, chain, rules):
    lines = [f"*{table}", f"-F {chain}"]
    lines.extend(f"-A {chain} {rule}" for rule in rules)
    lines.append("COMMIT")
    run_cmd(["iptables-restore", "--noflush"], check=True, input_text="\n".join(lines) + "\n")


def _ipset_restore(entries=(), set_name=IPSET_MAC_NAME):
    lines = [f"create {set_name} hash:mac family inet counters -exist"]
    lines.extend(f"add {set_name} {entry} -exist" for entry in entries)
    run_cmd(["ipset", "restore"], check=True, input_text="\n".join(lines) + "\n")


def get_mac_from_ip(ip_address):
    client_ip = _valid_ip(ip_address)
    if not client_ip or client_ip in {"127.0.0.1", "::1"}:
        return None
    try:
        with open("/proc/net/arp", encoding="ascii") as arp:
            for line in arp.readlines()[1:]:
                parts = line.split()
                mac = _valid_mac(parts[3]) if len(parts) >= 4 and parts[0] == client_ip else None
                if mac and mac != "00:00:00:00:00:00":
                    return mac
    except (OSError, UnicodeError) as exc:
        logger.warning("Error reading ARP table: %s", exc)
    for lease_path in ("/var/lib/misc/nigel-dnsmasq.leases", "/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases"):
        try:
            with open(lease_path, encoding="ascii") as leases:
                for line in leases:
                    parts = line.split()
                    mac = _valid_mac(parts[1]) if len(parts) >= 3 and parts[2] == client_ip else None
                    if mac:
                        return mac
        except (OSError, UnicodeError):
            continue
    result = run_cmd(["ip", "neigh", "show", client_ip])
    parts = result.split() if result else []
    if "lladdr" in parts:
        index = parts.index("lladdr") + 1
        if index < len(parts):
            return _valid_mac(parts[index])
    return None


def get_device_telemetry(mac_address):
    mac = _valid_mac(mac_address)
    if not mac:
        return {"hostname": None, "data_used_mb": 0.0, "signal_strength": None}
    hostname = None
    for lease_path in ("/var/lib/misc/nigel-dnsmasq.leases", "/var/lib/misc/dnsmasq.leases", "/var/lib/dnsmasq/dnsmasq.leases"):
        try:
            with open(lease_path, encoding="utf-8") as leases:
                for line in leases:
                    parts = line.split()
                    if len(parts) >= 4 and parts[1].lower() == mac:
                        hostname = parts[3] if parts[3] != "*" else None
                        break
        except OSError:
            continue
    signal = None
    if WIFI_IFACE:
        station_dump = run_cmd(["iw", "dev", _valid_iface(WIFI_IFACE), "station", "dump"])
        if station_dump:
            rows = station_dump.splitlines()
            for index, row in enumerate(rows):
                if row.strip().lower().startswith(mac):
                    for detail in rows[index:index + 12]:
                        if "signal:" in detail:
                            try:
                                signal = int(detail.split("signal:", 1)[1].split()[0])
                            except (ValueError, IndexError):
                                pass
                            break
    data_used_mb = 0.0
    saved = run_cmd(["ipset", "-o", "save", IPSET_MAC_NAME])
    if saved:
        for row in saved.splitlines():
            fields = row.split()
            if len(fields) >= 4 and fields[0] == "add" and fields[2] == mac:
                try:
                    data_used_mb = float(fields[fields.index("bytes") + 1]) / (1024 * 1024)
                except (ValueError, IndexError):
                    pass
                break
    return {"hostname": hostname, "data_used_mb": data_used_mb, "signal_strength": signal}


def init_ipset():
    _ipset_restore()
    _ipset_restore(set_name=IPSET_TRUSTED_NAME)


def add_device_to_ipset(mac_address=None, ip_address=None):
    mac = _valid_mac(mac_address)
    if mac:
        _ipset_restore([mac])


def add_trusted_device(mac_address):
    mac = _valid_mac(mac_address)
    if mac:
        _ipset_restore([mac], IPSET_TRUSTED_NAME)


def remove_trusted_device(mac_address):
    mac = _valid_mac(mac_address)
    if mac:
        run_cmd(["ipset", "del", IPSET_TRUSTED_NAME, mac, "-exist"])


def remove_device_from_ipset(mac_address=None, ip_address=None):
    mac = _valid_mac(mac_address)
    if mac:
        run_cmd(["ipset", "del", IPSET_MAC_NAME, mac, "-exist"])


def flush_ipset():
    run_cmd(["ipset", "flush", IPSET_MAC_NAME])


def _default_route_iface():
    output = run_cmd(["ip", "route", "show", "default"])
    if not output:
        return None
    parts = output.split()
    return parts[parts.index("dev") + 1] if "dev" in parts else None


def _configure_chains():
    iface = _valid_iface(WIFI_IFACE)
    _configured_ip()
    for table, chain, parent in CHAINS:
        if parent == "DOCKER-USER" and not _chain_exists(table, parent):
            logger.info("Docker is not installed; skipping %s", chain)
            continue
        _ensure_chain(table, chain, parent)

    _restore("nat", "NIGEL_NAT", [
        f"-i {iface} -m set --match-set {IPSET_TRUSTED_NAME} src -j RETURN",
        f"-i {iface} -m set --match-set {IPSET_MAC_NAME} src -j RETURN",
        f"-i {iface} -p tcp --dport 80 -j REDIRECT --to-ports 5000",
    ])
    input_rules = [
        f"-i {iface} -p udp --dport 67:68 -j ACCEPT",
        f"-i {iface} -p udp --dport 53 -j ACCEPT",
        f"-i {iface} -p tcp --dport 53 -j ACCEPT",
        f"-i {iface} -p tcp --dport 80 -j ACCEPT",
        f"-i {iface} -p tcp --dport 5000 -j ACCEPT",
        f"-i {iface} -m set --match-set {IPSET_TRUSTED_NAME} src -j ACCEPT",
        f"-i {iface} -m set --match-set {IPSET_MAC_NAME} src -j ACCEPT",
    ]
    if STRICT_MODE and _hotspot_active() and WIFI_SUBNET:
        input_rules.append(f"-i {iface} -s {WIFI_SUBNET} -j DROP")
    _restore("filter", "NIGEL_INPUT", input_rules)

    forward_rules = [
        "-m conntrack --ctstate RELATED,ESTABLISHED -j RETURN",
        f"-i {iface} -m set --match-set {IPSET_TRUSTED_NAME} src -j RETURN",
        f"-i {iface} -m set --match-set {IPSET_MAC_NAME} src -j RETURN",
    ]
    if STRICT_MODE and _hotspot_active() and WIFI_SUBNET:
        forward_rules.append(f"-i {iface} -s {WIFI_SUBNET} -j DROP")
    _restore("filter", "NIGEL_FWD", forward_rules)

    if _chain_exists("filter", "DOCKER-USER"):
        docker_rules = [
            f"-i {iface} -m set --match-set {IPSET_TRUSTED_NAME} src -j RETURN",
            f"-i {iface} -m set --match-set {IPSET_MAC_NAME} src -j RETURN",
        ]
        if STRICT_MODE and _hotspot_active() and WIFI_SUBNET:
            docker_rules.append(f"-i {iface} -s {WIFI_SUBNET} -j DROP")
        _restore("filter", "NIGEL_DOCKER_USER", docker_rules)

    wan = _default_route_iface()
    if wan and wan != iface and not _rule_exists("nat", "POSTROUTING", "-o", wan, "-j", "MASQUERADE"):
        _iptables("nat", "-A", "POSTROUTING", "-o", wan, "-j", "MASQUERADE", check=True)
        run_cmd(["sysctl", "-w", "net.ipv4.ip_forward=1"], check=True)
    logger.info("Nigel firewall chains applied for %s (strict=%s, wan=%s)", iface, STRICT_MODE, wan or "none")


def apply_iptables_rules():
    init_ipset()
    _configure_chains()
    start_watchdog()


def cleanup():
    for table, chain, parent in CHAINS:
        if _chain_exists(table, chain):
            while _rule_exists(table, parent, "-j", chain):
                _iptables(table, "-D", parent, "-j", chain)
            _iptables(table, "-F", chain)
            _iptables(table, "-X", chain)
    run_cmd(["ipset", "destroy", IPSET_MAC_NAME])
    run_cmd(["ipset", "destroy", IPSET_TRUSTED_NAME])
    logger.info("Nigel firewall chains and ipsets removed")


def _watchdog():
    while True:
        time.sleep(30)
        expected = [(table, chain, parent) for table, chain, parent in CHAINS
                if parent != "DOCKER-USER" or _chain_exists(table, parent)]
        broken = any(not _chain_exists(table, chain) or not _chain_has_rules(table, chain)
                 or not _rule_exists(table, parent, "-j", chain)
                 for table, chain, parent in expected)
        if broken:
            logger.warning("Nigel firewall was missing; repairing it")
            try:
                apply_iptables_rules()
            except Exception:
                logger.exception("Firewall repair failed")


def start_watchdog():
    global _watchdog_started
    if not _watchdog_started:
        _watchdog_started = True
        threading.Thread(target=_watchdog, name="nigel-firewall-watchdog", daemon=True).start()


def restart_dnsmasq():
    run_cmd(["systemctl", "restart", "dnsmasq"], check=True)
