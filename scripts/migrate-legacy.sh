#!/usr/bin/env bash
set -euo pipefail

if (($# == 0)); then
  echo 'Usage: migrate-legacy.sh [--apply] PATH...' >&2
  exit 2
fi
APPLY=0
paths=()
while (($#)); do
  case $1 in
    --apply) APPLY=1 ;;
    /*) paths+=("$1") ;;
    *) echo "Only explicit absolute paths are accepted: $1" >&2; exit 2 ;;
  esac
  shift
done
for path in "${paths[@]}"; do
  [[ -f $path ]] || { echo "Not a regular file: $path" >&2; exit 1; }
  printf '%s\n' "$path"
  if ((APPLY)); then
    backup="/var/backups/nigel/$(date +%Y%m%d-%H%M%S)"
    install -d -m 0700 "$backup"
    cp -a -- "$path" "$backup/"
    rm -f -- "$path"
  fi
done
