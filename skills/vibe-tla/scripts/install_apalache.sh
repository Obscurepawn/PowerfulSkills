#!/usr/bin/env bash
# install_apalache.sh — locate or download the Apalache symbolic model checker
# (apalache-mc + bundled Z3), smoke-test Snowcat + SMT checking, and record
# APALACHE_BIN in <workspace>/config.env without clobbering existing settings.
# Idempotent; invoked on demand when a level switches to symbolic reasoning
# (references/symbolic.md).
# Usage:
#   install_apalache.sh <workspace-dir>
# Honors env: APALACHE_BIN (use this binary), APALACHE_VERSION (default v0.63.0),
#             APALACHE_URL (download .tgz from here), APALACHE_TIMEOUT (seconds).
set -uo pipefail

WS="${1:-}"
[[ -n "$WS" ]] || { echo "usage: install_apalache.sh <workspace-dir>" >&2; exit 2; }
mkdir -p "$WS/tools"
WS_ABS="$(cd "$WS" && pwd)"
CONFIG="$WS_ABS/config.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

CLI_APALACHE_BIN="${APALACHE_BIN:-}"
CLI_APALACHE_TIMEOUT="${APALACHE_TIMEOUT:-}"

PRIOR_BIN=""
if [[ -f "$CONFIG" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG" 2>/dev/null || true
  PRIOR_BIN="${APALACHE_BIN:-}"
fi

# 1. Java 17+ is required by Apalache.
if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: java not found — Apalache requires a JRE (17+)." >&2
  exit 1
fi

find_apalache() {
  if [[ -n "$CLI_APALACHE_BIN" && -x "$CLI_APALACHE_BIN" ]]; then echo "$CLI_APALACHE_BIN"; return 0; fi
  if [[ -n "$PRIOR_BIN" && -x "$PRIOR_BIN" ]]; then echo "$PRIOR_BIN"; return 0; fi
  if [[ -x "$WS_ABS/tools/apalache/bin/apalache-mc" ]]; then echo "$WS_ABS/tools/apalache/bin/apalache-mc"; return 0; fi
  local p
  p="$(command -v apalache-mc 2>/dev/null || true)"
  if [[ -n "$p" && -x "$p" ]]; then echo "$p"; return 0; fi
  for p in /opt/apalache/bin/apalache-mc /usr/local/bin/apalache-mc "$HOME/.apalache/bin/apalache-mc"; do
    [[ -x "$p" ]] && { echo "$p"; return 0; }
  done
  return 1
}

BIN="$(find_apalache || true)"
if [[ -n "$BIN" ]]; then
  echo "Found apalache-mc: $BIN"
else
  PINNED_VER="${APALACHE_VERSION:-v0.63.0}"
  URL="${APALACHE_URL:-https://github.com/apalache-mc/apalache/releases/download/${PINNED_VER}/apalache.tgz}"
  ARCHIVE="$WS_ABS/tools/apalache.tgz"
  DEST_DIR="$WS_ABS/tools/apalache"
  echo "No apalache-mc found — downloading pinned release (${PINNED_VER}) from $URL"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 -o "$ARCHIVE" "$URL" || true
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$ARCHIVE" "$URL" || true
  else
    echo "ERROR: neither curl nor wget available to download Apalache." >&2
  fi
  if [[ -s "$ARCHIVE" ]]; then
    rm -rf "$DEST_DIR" 2>/dev/null || true
    mkdir -p "$DEST_DIR"
    if tar -xzf "$ARCHIVE" -C "$DEST_DIR" --strip-components=1 2>/dev/null \
       || tar -xzf "$ARCHIVE" -C "$DEST_DIR" 2>/dev/null; then
      rm -f "$ARCHIVE" 2>/dev/null || true
      if [[ -x "$DEST_DIR/bin/apalache-mc" ]]; then
        BIN="$DEST_DIR/bin/apalache-mc"
      else
        FOUND="$(find "$DEST_DIR" -type f -name 'apalache-mc' 2>/dev/null | head -1)"
        [[ -n "$FOUND" ]] && chmod +x "$FOUND" && BIN="$FOUND"
      fi
    fi
  fi
  if [[ -z "$BIN" || ! -x "$BIN" ]]; then
    rm -f "$ARCHIVE" 2>/dev/null || true
    echo "ERROR: could not obtain apalache-mc automatically." >&2
    echo "  Download $URL, extract to $DEST_DIR (so $DEST_DIR/bin/apalache-mc exists), then re-run install_apalache.sh." >&2
    exit 1
  fi
  echo "Downloaded: $BIN"
fi

# 2. Smoke-test Snowcat + SMT check in a throwaway dir.
echo "Verifying Apalache (Snowcat + Z3) runs ..."
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t vibeapa)"
cp "$SCRIPT_DIR/smoke/SmokeSymbolic.tla" "$TMP/" 2>/dev/null || true
SMOKE_OUT="$(cd "$TMP" && "$BIN" check --out-dir="$TMP/out" --init=Init --next=Next --inv=Inv --length=1 --no-deadlock SmokeSymbolic.tla 2>&1)"
SMOKE_RC=$?
rm -rf "$TMP" 2>/dev/null || true

if [[ "$SMOKE_RC" -eq 0 ]] && printf '%s\n' "$SMOKE_OUT" | grep -qE "NoError|Checker reports no error"; then
  echo "Apalache OK. Smoke result:"
  printf '%s\n' "$SMOKE_OUT" | grep -E "Type checker|NoError|Checker reports no error" | sed 's/^/  /'
else
  echo "ERROR: Apalache smoke check failed (exit $SMOKE_RC). Tail of output:" >&2
  printf '%s\n' "$SMOKE_OUT" | tail -12 >&2
  exit 1
fi

# 3. Record APALACHE_BIN (+ APALACHE_TIMEOUT) in config.env, preserving existing keys.
TIMEOUT_VAL="${CLI_APALACHE_TIMEOUT:-${APALACHE_TIMEOUT:-1800}}"
if [[ -f "$CONFIG" ]]; then
  TMP_CFG="$(mktemp "${CONFIG}.XXXXXX")"
  grep -vE '^(APALACHE_BIN|APALACHE_TIMEOUT)=' "$CONFIG" > "$TMP_CFG" || true
  {
    printf 'APALACHE_BIN=%s\n' "$BIN"
    printf 'APALACHE_TIMEOUT=%s\n' "$TIMEOUT_VAL"
  } >> "$TMP_CFG"
  mv "$TMP_CFG" "$CONFIG"
else
  REPO_ROOT="$(dirname "$WS_ABS")"
  WORKSPACE_DIR="$(basename "$WS_ABS")"
  cat > "$CONFIG" <<EOF
# vibe-tla machine settings — written by install_apalache.sh
REPO_ROOT=$REPO_ROOT
WORKSPACE_DIR=$WORKSPACE_DIR
APALACHE_BIN=$BIN
APALACHE_TIMEOUT=$TIMEOUT_VAL
EOF
fi

echo "Updated $CONFIG"
echo "  APALACHE_BIN=$BIN"
echo "  APALACHE_TIMEOUT=$TIMEOUT_VAL"
