#!/usr/bin/env bash
set -u

pass=0
fail=0
check() {
  local label="$1"
  shift
  if "$@"; then
    printf 'PASS: %s\n' "$label"
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$label"
    fail=$((fail + 1))
  fi
}

printf '%s\n' 'Nigel Server preflight (read-only)'
if [[ -r /etc/os-release ]]; then
  . /etc/os-release
  printf 'OS: %s %s\n' "${NAME:-unknown}" "${VERSION_ID:-unknown}"
  check 'Ubuntu 22.04, 24.04, or 26.04' test "${ID:-}" = ubuntu -a \( "${VERSION_ID:-}" = 22.04 -o "${VERSION_ID:-}" = 24.04 -o "${VERSION_ID:-}" = 26.04 \)
else
  check 'Ubuntu release metadata' false
fi

if command -v node >/dev/null 2>&1; then
  node_major=$(node -p 'process.versions.node.split(".")[0]')
  printf 'Node: %s\n' "$(node --version)"
  check 'Node.js 18 or newer' test "$node_major" -ge 18
else
  check 'Node.js installed' false
fi

if command -v iw >/dev/null 2>&1; then
  check 'Wi-Fi AP mode supported' bash -c 'iw list 2>/dev/null | grep -q AP'
else
  check 'iw installed' false
fi

if command -v iptables-restore >/dev/null 2>&1; then
  printf 'iptables: %s\n' "$(iptables --version 2>/dev/null || true)"
  check 'iptables-restore nft syntax' bash -c 'printf "%s\\n" "*nat" ":NIGEL_PREFLIGHT - [0:0]" "-A NIGEL_PREFLIGHT -m set --match-set nigel_auth_macs src -j RETURN" "COMMIT" | iptables-restore --test --noflush'
else
  check 'iptables-restore installed' false
fi

if command -v networkctl >/dev/null 2>&1 && systemctl is-active --quiet systemd-networkd; then
  printf '%s\n' 'Renderer: systemd-networkd'
elif command -v nmcli >/dev/null 2>&1 && systemctl is-active --quiet NetworkManager; then
  printf '%s\n' 'Renderer: NetworkManager'
else
  printf '%s\n' 'Renderer: unknown'
  fail=$((fail + 1))
fi

if command -v ufw >/dev/null 2>&1; then
  ufw status | grep -q 'Status: active' && printf '%s\n' 'WARN: ufw is active' || printf '%s\n' 'PASS: ufw inactive'
else
  printf '%s\n' 'PASS: ufw not installed'
fi

for port in 53 80 5000; do
  if ss -H -ltnup "sport = :$port" 2>/dev/null | grep -q .; then
    printf 'WARN: port %s is already in use\n' "$port"
  else
    printf 'PASS: port %s is available\n' "$port"
  fi
done

printf '%s\n' 'Existing hotspot configuration:'
find /etc/dnsmasq.d /etc/default/dnsmasq -maxdepth 1 -type f -print 2>/dev/null || true
printf '%s\n' 'Existing Nigel firewall state:'
iptables -S 2>/dev/null | grep -E 'NIGEL|nigel' || true
ipset list 2>/dev/null | grep -E 'Name: nigel|nigel_' || true
printf 'Summary: %s passed, %s failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
