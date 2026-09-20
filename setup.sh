#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STATE_DIR=/etc/nigel
ENV_FILE=$STATE_DIR/nigel.env
WIFI_IFACE=${WIFI_IFACE:-}
SKIP_FRONTEND_BUILD=${SKIP_FRONTEND_BUILD:-0}

usage() {
  cat <<'EOF'
Usage:
  sudo ./setup.sh install          Install packages, Python dependencies, and frontend assets.
  sudo ./setup.sh enable-hotspot   Configure and activate the Wi-Fi hotspot.

The commands are intentionally separate: install requires internet and never changes
network configuration; enable-hotspot switches the selected Wi-Fi card to AP mode.
EOF
}

require_root() { [[ $EUID -eq 0 ]] || { echo 'Run as root: sudo ./setup.sh ...' >&2; exit 1; }; }
require_ubuntu() {
  command -v apt-get >/dev/null || { echo 'Ubuntu apt-get is required' >&2; exit 1; }
  . /etc/os-release
  [[ ${ID:-} == ubuntu ]] || { echo 'Ubuntu is required' >&2; exit 1; }
  case ${VERSION_ID:-} in 22.04|24.04|26.04) ;; *) echo 'Supported Ubuntu versions: 22.04, 24.04, 26.04' >&2; exit 1 ;; esac
}

install_phase() {
  require_root
  require_ubuntu
  bash "$ROOT_DIR/scripts/preflight.sh" || echo 'Preflight reported issues; review them before enabling the hotspot.'
  systemctl mask --runtime dnsmasq.service hostapd.service 2>/dev/null || true
  trap 'systemctl unmask dnsmasq.service hostapd.service 2>/dev/null || true' EXIT
  apt-get update
  apt-get install -y python3 python3-venv python3-pip iptables ipset dnsmasq hostapd iw wpa-supplicant isc-dhcp-client curl gettext-base build-essential
  if ! command -v node >/dev/null 2>&1 || (( $(node -p 'process.versions.node.split(".")[0]') < 18 )); then
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
    apt-get install -y nodejs
  fi
  python3 -m venv "$ROOT_DIR/venv"
  "$ROOT_DIR/venv/bin/pip" install --upgrade pip
  "$ROOT_DIR/venv/bin/pip" install -r "$ROOT_DIR/backend/requirements.txt"
  if [[ $SKIP_FRONTEND_BUILD != 1 ]]; then
    if [[ -f "$ROOT_DIR/frontend/package-lock.json" ]]; then
      (cd "$ROOT_DIR/frontend" && npm ci && npm run build)
    else
      (cd "$ROOT_DIR/frontend" && npm install && npm run build)
    fi
  fi
  [[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || { echo 'frontend/dist/index.html is missing; build it or set SKIP_FRONTEND_BUILD=1'; exit 1; }
  install -d -m 0755 "$STATE_DIR" /var/lib/nigel-server
  trap - EXIT
  systemctl unmask dnsmasq.service hostapd.service 2>/dev/null || true
  echo "Install complete. Run: sudo $ROOT_DIR/setup.sh enable-hotspot"
}

enable_phase() {
  require_root
  require_ubuntu
  command -v envsubst >/dev/null || { echo 'gettext-base is missing; run setup.sh install first' >&2; exit 1; }
  [[ -x "$ROOT_DIR/venv/bin/python" ]] || { echo 'Python environment missing; run setup.sh install first' >&2; exit 1; }
  [[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || { echo 'frontend/dist/index.html missing; run setup.sh install or provide a prebuilt dist' >&2; exit 1; }

  if [[ -z $WIFI_IFACE ]]; then
    WIFI_IFACE=$(find /sys/class/net -maxdepth 1 -type l -printf '%f\n' | grep -E '^(wl|wlan)' | head -n 1 || true)
  fi
  [[ -n $WIFI_IFACE ]] || { echo 'No Wi-Fi interface found; set WIFI_IFACE=wlo1' >&2; exit 1; }
  [[ $WIFI_IFACE =~ ^[A-Za-z0-9_.:-]{1,15}$ ]] || { echo 'Invalid Wi-Fi interface' >&2; exit 1; }
  iw dev "$WIFI_IFACE" info >/dev/null 2>&1 || { echo "Wi-Fi interface not found: $WIFI_IFACE" >&2; exit 1; }
  iw list | awk '/valid interface combinations:/,/Supported commands:/' | grep -q AP || { echo 'The Wi-Fi card does not advertise AP mode' >&2; exit 1; }

  local wifi_ip=10.0.0.1 wifi_prefix=24 ssid passphrase existing_passphrase escaped
  ssid=${WIFI_SSID:-Nigel Server}
  existing_passphrase=''
  if [[ -r /etc/hostapd/hostapd.conf ]]; then
    existing_passphrase=$(awk -F= '$1 == "wpa_passphrase" {print substr($0, index($0, "=") + 1); exit}' /etc/hostapd/hostapd.conf)
  fi
  read -r -s -p 'WPA2 passphrase (Enter keeps the existing passphrase; type OPEN for open network): ' passphrase
  printf '\n'
  if [[ -z $passphrase ]]; then passphrase=$existing_passphrase; fi
  if [[ $passphrase == OPEN ]]; then passphrase=''; fi
  if [[ -n $passphrase && ( ${#passphrase} -lt 8 || ${#passphrase} -gt 63 || $passphrase == *$'\n'* ) ]]; then
    echo 'WPA2 passphrase must be 8-63 characters and contain no newline.' >&2
    exit 1
  fi
  [[ $ssid != *$'\n'* ]] || { echo 'SSID cannot contain a newline.' >&2; exit 1; }
  install -d -m 0755 "$STATE_DIR" /var/lib/nigel-server /etc/hostapd
  umask 077
  write_env_value() {
    local key=$1 value=$2
    escaped=${value//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    escaped=${escaped//\$/\\\$}
    escaped=${escaped//\`/\\\`}
    printf '%s="%s"\n' "$key" "$escaped"
  }
  {
    write_env_value WIFI_IFACE "$WIFI_IFACE"
    write_env_value NIGEL_WIFI_IP "$wifi_ip"
    write_env_value NIGEL_WIFI_PREFIX "$wifi_prefix"
    write_env_value NIGEL_WIFI_NETMASK '255.255.255.0'
    write_env_value NIGEL_DHCP_START '10.0.0.10'
    write_env_value NIGEL_DHCP_END '10.0.0.250'
    write_env_value NIGEL_STRICT '1'
    write_env_value WIFI_SSID "$ssid"
    write_env_value WIFI_PASSPHRASE "$passphrase"
    write_env_value PORTAL_ORIGIN "http://$wifi_ip:5000"
    write_env_value NIGEL_STATE_DIR '/var/lib/nigel-server'
    write_env_value NIGEL_ROOT "$ROOT_DIR"
  } > "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  set -a
  . "$ENV_FILE"
  set +a

  envsubst < "$ROOT_DIR/config_templates/dnsmasq.conf" > "$STATE_DIR/dnsmasq.conf"
  envsubst < "$ROOT_DIR/config_templates/hostapd.conf" > /etc/hostapd/hostapd.conf
  if [[ -n $WIFI_PASSPHRASE ]]; then
    cat >> /etc/hostapd/hostapd.conf <<EOF
wpa=2
wpa_passphrase=$WIFI_PASSPHRASE
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
  fi

  # Ignore every old dnsmasq.d fragment, including ubuntu-fan, for this dedicated hotspot.
  if [[ -e /etc/default/dnsmasq ]]; then cp -a /etc/default/dnsmasq "/etc/default/dnsmasq.nigel-backup.$(date +%s)"; fi
  printf '%s\n' 'CONFIG_DIR=' > /etc/default/dnsmasq
  dnsmasq --test --conf-file="$STATE_DIR/dnsmasq.conf" --conf-dir=

  install -m 0755 "$ROOT_DIR/scripts/nigel-hotspot" /usr/local/sbin/nigel-hotspot
  legacy_backup="/root/nigel-backup-$(date +%Y%m%d-%H%M%S)"
  install -d -m 0700 "$legacy_backup"
  systemctl stop nigelserver-boot.service 2>/dev/null || true
  systemctl disable nigelserver-boot.service 2>/dev/null || true
  rm -f /etc/systemd/system/nigelserver-boot.service
  for legacy_script in /home/nigel/nigelserver-on.sh /home/nigel/nigelserver-off.sh /home/nigel/internet-on.sh /home/nigel/internet-off.sh; do
    if [[ -e "$legacy_script" ]]; then
      cp -a "$legacy_script" "$legacy_backup/"
      rm -f "$legacy_script"
    fi
  done
  cat > /etc/systemd/system/nigel-server.service <<EOF
[Unit]
Description=Nigel Server Captive Portal Backend
After=network-online.target hostapd.service dnsmasq.service
Wants=network-online.target

[Service]
User=root
WorkingDirectory=$ROOT_DIR/backend
EnvironmentFile=$ENV_FILE
ExecStart=$ROOT_DIR/venv/bin/python app.py
Restart=on-failure
RestartSec=2

[Install]
WantedBy=multi-user.target
EOF
  install -d -m 0755 /etc/systemd/system/hostapd.service.d /etc/systemd/system/dnsmasq.service.d
  cat > /etc/systemd/system/hostapd.service.d/nigel.conf <<EOF
[Unit]
After=network-online.target
Wants=network-online.target
[Service]
Restart=on-failure
RestartSec=2
EOF
  cat > /etc/systemd/system/dnsmasq.service.d/nigel.conf <<EOF
[Unit]
After=hostapd.service
[Service]
Type=simple
PIDFile=
ExecStart=
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=$STATE_DIR/dnsmasq.conf --conf-dir=
Restart=on-failure
RestartSec=2
EOF
  cat > /etc/systemd/system/nigel-hotspot.service <<EOF
[Unit]
Description=Nigel Server hotspot lifecycle
After=network.target
Before=hostapd.service dnsmasq.service nigel-server.service
[Service]
Type=oneshot
RemainAfterExit=yes
Environment=NIGEL_HOTSPOT_UNIT=1
ExecStart=/usr/local/sbin/nigel-hotspot on
ExecStop=/usr/local/sbin/nigel-hotspot off
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable nigel-hotspot.service
  systemctl start nigel-hotspot.service
  systemctl --no-pager --full status nigel-hotspot.service hostapd dnsmasq nigel-server
  printf 'Hotspot enabled on %s. To return to client Wi-Fi: sudo nigel-hotspot off\n' "$WIFI_IFACE"
}

case "${1:-}" in
  install) install_phase ;;
  enable-hotspot) enable_phase ;;
  *) usage; exit 2 ;;
esac
