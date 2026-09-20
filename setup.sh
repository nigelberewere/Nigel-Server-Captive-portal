#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
STATE_DIR=/etc/nigel
ENV_FILE=$STATE_DIR/nigel.env
CONFIG_FILE=${NIGEL_CONFIG:-$STATE_DIR/nigel.conf}
WIFI_IFACE=${WIFI_IFACE:-}
SKIP_FRONTEND_BUILD=${SKIP_FRONTEND_BUILD:-0}

usage() {
  cat <<'EOF'
Usage:
  sudo ./setup.sh install          Install packages, Python dependencies, and frontend assets.
  sudo ./setup.sh enable-hotspot   Configure the Wi-Fi hotspot for next boot.

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
  apt-get install -y python3 python3-venv python3-pip iptables ipset dnsmasq hostapd iw wpasupplicant nodejs npm curl gettext-base build-essential
  if ! command -v node >/dev/null 2>&1 || (( $(node -p 'process.versions.node.split(".")[0]') < 18 )); then
    if [[ ${ALLOW_NODESOURCE:-0} == 1 ]]; then
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
      apt-get install -y nodejs
    else
      echo 'Node.js 18+ is required. Install it from a trusted package source or rerun with ALLOW_NODESOURCE=1.' >&2
      exit 1
    fi
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
  if [[ -r $CONFIG_FILE ]]; then
      install -d -m 0755 "$STATE_DIR" /var/lib/nigel-server
    . "$CONFIG_FILE"
    set +a
  fi
  [[ -x "$ROOT_DIR/venv/bin/python" ]] || { echo 'Python environment missing; run setup.sh install first' >&2; exit 1; }
  [[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || { echo 'frontend/dist/index.html missing; run setup.sh install or provide a prebuilt dist' >&2; exit 1; }

  if [[ -z $WIFI_IFACE ]]; then WIFI_IFACE=${AP_IFACE:-}; fi
  if [[ -z $WIFI_IFACE ]]; then
    WIFI_IFACE=$(find /sys/class/net -maxdepth 1 -type l -printf '%f\n' | grep -E '^(wl|wlan)' | head -n 1 || true)
  fi
  [[ -n $WIFI_IFACE ]] || { echo 'No Wi-Fi interface found; set WIFI_IFACE=wlo1' >&2; exit 1; }
  [[ $WIFI_IFACE =~ ^[A-Za-z0-9_.:-]{1,15}$ ]] || { echo 'Invalid Wi-Fi interface' >&2; exit 1; }
  iw dev "$WIFI_IFACE" info >/dev/null 2>&1 || { echo "Wi-Fi interface not found: $WIFI_IFACE" >&2; exit 1; }
  phy=$(iw dev "$WIFI_IFACE" info | awk '$1 == "wiphy" {print "phy" $2; exit}')
  [[ -n $phy ]] || { echo "Could not determine PHY for $WIFI_IFACE" >&2; exit 1; }
  iw phy "$phy" info | awk '/Supported interface modes:/,/Band [0-9]+:/' | grep -qE '^\s*\* AP$' || {
    echo "PHY $phy does not advertise AP mode" >&2
    exit 1
  }

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
  install -d -m 0755 "$STATE_DIR" /var/lib/nigel-server
  : > "$STATE_DIR/manifest"
  chmod 0600 "$STATE_DIR/manifest"
  printf '%s\n' /etc/nigel/nigel.env /etc/nigel/dnsmasq.conf /etc/nigel/hostapd.conf /etc/nigel/wifi-passphrase \
    /etc/systemd/system/nigel-server.service /etc/systemd/system/nigel-hotspot.service \
    /etc/systemd/system/nigel-hostapd.service /etc/systemd/system/nigel-dnsmasq.service \
    /etc/sysctl.d/99-nigel-hotspot.conf \
    /usr/local/sbin/nigel-hotspot >> "$STATE_DIR/manifest"
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
    write_env_value NIGEL_WIFI_SUBNET '10.0.0.0/24'
    write_env_value NIGEL_WIFI_NETMASK '255.255.255.0'
    write_env_value NIGEL_DHCP_START '10.0.0.10'
    write_env_value NIGEL_DHCP_END '10.0.0.250'
    write_env_value NIGEL_STRICT '1'
    write_env_value WIFI_SSID "$ssid"
    write_env_value WIFI_PASSPHRASE_FILE '/etc/nigel/wifi-passphrase'
    write_env_value NIGEL_CONFIG_DIR "$STATE_DIR"
    write_env_value PORTAL_ORIGIN "http://$wifi_ip:5000"
    write_env_value NIGEL_STATE_DIR '/var/lib/nigel-server'
    write_env_value NIGEL_ROOT "$ROOT_DIR"
  } > "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  printf '%s\n' "$passphrase" > "$STATE_DIR/wifi-passphrase"
  chmod 0600 "$STATE_DIR/wifi-passphrase"
  printf 'net.ipv6.conf.%s.disable_ipv6=1\n' "$WIFI_IFACE" > /etc/sysctl.d/99-nigel-hotspot.conf
  chmod 0644 /etc/sysctl.d/99-nigel-hotspot.conf
  set -a
  . "$ENV_FILE"
  set +a

  envsubst < "$ROOT_DIR/config_templates/dnsmasq.conf" > "$STATE_DIR/dnsmasq.conf"
  envsubst < "$ROOT_DIR/config_templates/hostapd.conf" > "$STATE_DIR/hostapd.conf"
  if [[ -n $passphrase ]]; then
    cat >> "$STATE_DIR/hostapd.conf" <<EOF
wpa=2
wpa_passphrase=$passphrase
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
EOF
  fi

  # The dedicated unit passes --conf-dir= and never reads package dnsmasq fragments.
  dnsmasq --test --conf-file="$STATE_DIR/dnsmasq.conf" --conf-dir=

  install -m 0755 "$ROOT_DIR/scripts/nigel-hotspot" /usr/local/sbin/nigel-hotspot
  cat > /etc/systemd/system/nigel-hostapd.service <<EOF
[Unit]
Description=Nigel hostapd
Requires=nigel-hotspot.service
After=nigel-hotspot.service
[Service]
ExecStart=/usr/sbin/hostapd $STATE_DIR/hostapd.conf
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/nigel-dnsmasq.service <<EOF
[Unit]
Description=Nigel dnsmasq
Requires=nigel-hotspot.service
After=nigel-hotspot.service nigel-hostapd.service
[Service]
ExecStart=/usr/sbin/dnsmasq --keep-in-foreground --conf-file=$STATE_DIR/dnsmasq.conf --conf-dir=
Restart=on-failure
RestartSec=2
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/nigel-server.service <<EOF
[Unit]
Description=Nigel Server Captive Portal Backend
Requires=nigel-hotspot.service nigel-dnsmasq.service
After=nigel-dnsmasq.service

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
  cat > /etc/systemd/system/nigel-hotspot.service <<EOF
[Unit]
Description=Nigel Server hotspot lifecycle
After=network.target
Before=nigel-hostapd.service nigel-dnsmasq.service nigel-server.service
[Service]
Type=oneshot
RemainAfterExit=yes
Environment=NIGEL_HOTSPOT_UNIT=1
ExecStart=/usr/local/sbin/nigel-hotspot prepare
ExecStop=/usr/local/sbin/nigel-hotspot release
[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl disable --now hostapd.service dnsmasq.service 2>/dev/null || true
  systemctl enable nigel-hotspot.service
  printf 'Hotspot configured on %s for next boot. Run sudo nigel-hotspot on --now to switch immediately.\n' "$WIFI_IFACE"
}

case "${1:-}" in
  install) install_phase ;;
  enable-hotspot) enable_phase ;;
  *) usage; exit 2 ;;
esac
