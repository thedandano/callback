#!/usr/bin/env bash
set -euo pipefail

base_version="$(
  python3 - <<'PY'
import tomllib

with open("pyproject.toml", "rb") as handle:
    data = tomllib.load(handle)

print(data["project"]["version"])
PY
)"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  printf '%s\n' "$base_version"
  exit 0
fi

base_ref="${CALLBACK_VERSION_BASE_REF:-origin/main}"
short_hash="$(git rev-parse --short HEAD)"
dirty=""

if ! git diff --quiet --ignore-submodules -- || ! git diff --cached --quiet --ignore-submodules --; then
  dirty="-dirty"
fi

if git rev-parse --verify "$base_ref" >/dev/null 2>&1; then
  ahead_count="$(git rev-list --count "${base_ref}..HEAD")"
else
  ahead_count="0"
fi

if [ "$ahead_count" -gt 0 ]; then
  printf '%s-%02d-%s%s\n' "$base_version" "$ahead_count" "$short_hash" "$dirty"
elif [ -n "$dirty" ]; then
  printf '%s-00-%s%s\n' "$base_version" "$short_hash" "$dirty"
else
  printf '%s\n' "$base_version"
fi
