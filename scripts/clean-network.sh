#!/usr/bin/env bash
set -euo pipefail

MANIFEST=/etc/nigel/manifest
APPLY=0
REMOVE_LEGACY=()
usage() {
  cat <<'EOF'
Usage: clean-network.sh [--dry-run] [--apply] [--remove-legacy PATH]

Dry-run is the default. Only --apply removes files listed in /etc/nigel/manifest.
Legacy findings are reported; use --remove-legacy with an explicit path to remove one.
EOF
}
while (($#)); do
  case $1 in
    --apply) APPLY=1 ;;
    --dry-run) APPLY=0 ;;
    --remove-legacy) (($# >= 2)) || { echo '--remove-legacy needs a path' >&2; exit 2; }; REMOVE_LEGACY+=("$2"); shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

printf '%s\n' 'Legacy address writers (reported only):'
for root in /etc/systemd/system /etc/systemd/network /etc/netplan /etc/network /etc/cron.d /etc/cron.hourly; do
  [[ -d $root ]] || continue
  grep -RIn --exclude='*.key' --exclude='*.pem' '192\.168\.4\.1' "$root" 2>/dev/null || true
done

if ((${#REMOVE_LEGACY[@]})); then
  for path in "${REMOVE_LEGACY[@]}"; do
    [[ -f $path ]] || { echo "Legacy path is not a regular file: $path" >&2; exit 1; }
    printf 'Explicit legacy removal requested: %s\n' "$path"
    if ((APPLY)); then
      backup_dir="/var/backups/nigel/$(date +%Y%m%d-%H%M%S)"
      install -d -m 0700 "$backup_dir"
      cp -a -- "$path" "$backup_dir/"
      rm -f -- "$path"
    fi
  done
fi

if [[ ! -r $MANIFEST ]]; then
  echo "No manifest at $MANIFEST; nothing to remove."
  exit 0
fi

if ((APPLY)) && [[ -r /etc/nigel/nigel.env ]]; then
  . /etc/nigel/nigel.env
  if [[ -n "${WIFI_IFACE:-}" ]]; then
    sysctl -w "net.ipv6.conf.$WIFI_IFACE.disable_ipv6=0" >/dev/null 2>&1 || true
  fi
fi

backup_dir="/var/backups/nigel/$(date +%Y%m%d-%H%M%S)"
while IFS= read -r path; do
  [[ -n $path && $path == /* ]] || continue
  printf '%s %s\n' "$([[ $APPLY -eq 1 ]] && echo REMOVE || echo WOULD_REMOVE)" "$path"
  if ((APPLY)) && [[ -e $path || -L $path ]]; then
    install -d -m 0700 "$backup_dir"
    cp -a -- "$path" "$backup_dir/"
    rm -f -- "$path"
  fi
done < "$MANIFEST"

if ((APPLY)); then
  rm -f -- "$MANIFEST"
  printf 'Backup: %s\n' "$backup_dir"
else
  echo 'Dry-run only. Re-run with --apply after reviewing the manifest.'
fi
