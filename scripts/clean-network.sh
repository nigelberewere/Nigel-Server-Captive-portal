#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
[[ "${1:-}" == "--dry-run" ]] && DRY_RUN=1
run() {
  printf '+ %q ' "$@"
  printf '\n'
  (( DRY_RUN )) || "$@"
}

if (( ! DRY_RUN )); then
  read -r -p 'Back up and remove Nigel hotspot configuration? Type YES: ' answer
  [[ "$answer" == YES ]] || { echo 'Cancelled.'; exit 1; }
fi

backup="/root/nigel-backup-$(date +%Y%m%d-%H%M%S)"
run mkdir -p "$backup"
for path in /etc/nigel /etc/dnsmasq.conf /etc/dnsmasq.d /etc/default/dnsmasq /etc/hostapd/hostapd.conf /etc/netplan /etc/network /etc/NetworkManager /etc/systemd/system /etc/systemd/network /etc/rc.local /etc/cron.d /etc/cron.hourly /home/nigel; do
  [[ -e "$path" ]] && run cp -a "$path" "$backup/"
done

if [[ -r /etc/nigel/nigel.env ]]; then
  . /etc/nigel/nigel.env
fi

printf '%s\n' 'Legacy 192.168.4.1 references (credentials are not printed):'
legacy_files=$(grep -RIl --exclude='*.key' --exclude='*.pem' '192\.168\.4\.1' /etc/systemd/system /etc/systemd/network /etc/netplan /etc/network /etc/rc.local /etc/cron.d /etc/cron.hourly /home/nigel 2>/dev/null || true)
if [[ -n "$legacy_files" ]]; then
  printf '%s\n' "$legacy_files"
  while IFS= read -r file; do
    [[ -n "$file" ]] && run sed -i '/192\.168\.4\.1/d' "$file"
  done <<< "$legacy_files"
else
  echo 'None found.'
fi

for unit in nigel-hotspot nigel-server nigelserver-boot dnsmasq hostapd restore-wifi-ip; do
  run systemctl stop "$unit.service" || true
  run systemctl disable "$unit.service" || true
done
run systemctl unmask "wpa_supplicant@.service" || true
run rm -f /etc/dnsmasq.d/* /etc/default/dnsmasq /etc/dnsmasq.conf /etc/hostapd/hostapd.conf
run rm -f /etc/systemd/system/nigel-hotspot.service /etc/systemd/system/nigel-server.service /etc/systemd/system/restore-wifi-ip.service
run rm -f /etc/systemd/system/hostapd.service.d/nigel.conf /etc/systemd/system/dnsmasq.service.d/nigel.conf
run rm -f /etc/systemd/network/90-nigel-wifi.network /etc/NetworkManager/system-connections/nigel-hotspot.nmconnection
run rm -f /etc/NetworkManager/conf.d/99-unmanaged-wlan.conf /etc/sudoers.d/nigel /etc/nigel/nigel.env
run rm -f /usr/local/sbin/nigel-hotspot
run rm -f /home/nigel/nigelserver-on.sh /home/nigel/nigelserver-off.sh /home/nigel/internet-on.sh /home/nigel/internet-off.sh
while IFS= read -r old_script; do
  [[ -n "$old_script" ]] && run rm -f "$old_script"
done < <(find /home/nigel -maxdepth 1 -type f \( -iname '*nigel*on*.sh' -o -iname '*nigel*off*.sh' \) -print 2>/dev/null)

if [[ -n "${WIFI_IFACE:-}" && -n "${NIGEL_WIFI_IP:-}" && -n "${NIGEL_WIFI_PREFIX:-}" ]]; then
  run ip addr del "${NIGEL_WIFI_IP}/${NIGEL_WIFI_PREFIX}" dev "$WIFI_IFACE" || true
fi
run iptables -w -t nat -D PREROUTING -j NIGEL_NAT || true
run iptables -w -t nat -F NIGEL_NAT || true
run iptables -w -t nat -X NIGEL_NAT || true
run iptables -w -D INPUT -j NIGEL_INPUT || true
run iptables -w -F NIGEL_INPUT || true
run iptables -w -X NIGEL_INPUT || true
run iptables -w -D FORWARD -j NIGEL_FWD || true
run iptables -w -F NIGEL_FWD || true
run iptables -w -X NIGEL_FWD || true
run iptables -w -D DOCKER-USER -j NIGEL_DOCKER_USER || true
run iptables -w -F NIGEL_DOCKER_USER || true
run iptables -w -X NIGEL_DOCKER_USER || true
run ipset destroy nigel_auth_macs || true
run ipset destroy nigel_trusted_macs || true
run systemctl daemon-reload
printf 'Backup: %s\n' "$backup"
