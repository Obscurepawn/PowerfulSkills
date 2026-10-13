#!/usr/bin/env bash
# install_tlc.sh — locate or download tla2tools.jar, verify TLC runs, and record
# the toolchain in <workspace>/config.env.  Idempotent.  Usage:
#   install_tlc.sh <workspace-dir>
# Honors env: TLA_TOOLS_JAR (use this jar), TLA_TOOLS_URL (download from here).
set -uo pipefail

WS="${1:-}"
[[ -n "$WS" ]] || { echo "usage: install_tlc.sh <workspace-dir>" >&2; exit 2; }
mkdir -p "$WS/tools"
WS_ABS="$(cd "$WS" && pwd)"
REPO_ROOT="$(dirname "$WS_ABS")"
WORKSPACE_DIR="$(basename "$WS_ABS")"
CONFIG="$WS_ABS/config.env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Capture any caller-supplied overrides BEFORE sourcing config.env, so that a refresh which
# passes a new value (e.g. `VIBE_TLA_EFFORT=high install_tlc.sh WS`) takes precedence over
# whatever the recorded config.env already holds.
CLI_TLC_WORKERS="${TLC_WORKERS:-}"
CLI_TLC_TIMEOUT="${TLC_TIMEOUT:-}"
CLI_VIBE_TLA_EFFORT="${VIBE_TLA_EFFORT:-}"
CLI_REPO_MODE="${REPO_MODE:-}"
CLI_REPO_URL="${REPO_URL:-}"

# Load any previously recorded values so a refresh re-uses them when no override is given.
PRIOR_JAR=""
if [[ -f "$CONFIG" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG" 2>/dev/null || true
  PRIOR_JAR="${TLA_TOOLS_JAR:-}"
fi

# 1. Java is mandatory and cannot be installed silently.
if ! command -v java >/dev/null 2>&1; then
  echo "ERROR: java not found — TLC needs a JRE (17+ recommended)." >&2
  echo "  macOS:  brew install openjdk" >&2
  echo "  Linux:  install your distro's JDK 17 package (e.g. apt install openjdk-17-jre)" >&2
  exit 1
fi

find_jar() {
  if [[ -n "${TLA_TOOLS_JAR:-}" && -f "${TLA_TOOLS_JAR:-}" ]]; then echo "$TLA_TOOLS_JAR"; return 0; fi
  if [[ -n "$PRIOR_JAR" && -f "$PRIOR_JAR" ]]; then echo "$PRIOR_JAR"; return 0; fi
  if [[ -f "$WS_ABS/tools/tla2tools.jar" ]]; then echo "$WS_ABS/tools/tla2tools.jar"; return 0; fi
  local j
  for j in "$HOME"/.vscode*/extensions/tlaplus.vscode-ide-*/tools/tla2tools.jar; do
    [[ -f "$j" ]] && { echo "$j"; return 0; }
  done
  for j in /usr/local/lib/tla2tools.jar /opt/tlaplus/tla2tools.jar "$HOME/.tlaplus/tla2tools.jar"; do
    [[ -f "$j" ]] && { echo "$j"; return 0; }
  done
  return 1
}

JAR="$(find_jar || true)"
if [[ -n "$JAR" ]]; then
  echo "Found tla2tools.jar: $JAR"
else
  URL="${TLA_TOOLS_URL:-https://github.com/tlaplus/tlaplus/releases/latest/download/tla2tools.jar}"
  DEST="$WS_ABS/tools/tla2tools.jar"
  echo "No tla2tools.jar found — downloading from $URL"
  if command -v curl >/dev/null 2>&1; then
    curl -fL --retry 3 -o "$DEST" "$URL" || true
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O "$DEST" "$URL" || true
  else
    echo "ERROR: neither curl nor wget available to download the jar." >&2
  fi
  if [[ -s "$DEST" ]]; then
    JAR="$DEST"
    echo "Downloaded: $JAR"
  else
    echo "ERROR: could not obtain tla2tools.jar automatically." >&2
    echo "  Download it from $URL and place it at $DEST, then re-run /vibe-tla init." >&2
    exit 1
  fi
fi

# 2. Smoke-test TLC in a throwaway dir (skill dir may be read-only).
echo "Verifying TLC runs ..."
TMP="$(mktemp -d 2>/dev/null || mktemp -d -t vibetla)"
cp "$SCRIPT_DIR/smoke/Smoke.tla" "$SCRIPT_DIR/smoke/Smoke.cfg" "$TMP/" 2>/dev/null || true
SMOKE_OUT="$(cd "$TMP" && java -cp "$JAR" tlc2.TLC -config Smoke.cfg Smoke.tla 2>&1)"
rm -rf "$TMP" 2>/dev/null || true
if printf '%s\n' "$SMOKE_OUT" | grep -qE "No error has been found|Model checking completed"; then
  echo "TLC OK. Smoke result:"
  printf '%s\n' "$SMOKE_OUT" \
    | grep -E "Model checking completed|No error has been found|states generated|distinct states" \
    | sed 's/^/  /'
else
  echo "WARNING: TLC smoke check did not report success. Tail of output:" >&2
  printf '%s\n' "$SMOKE_OUT" | tail -6 >&2
fi

# 3. Record the toolchain.  Precedence per key: caller override > recorded value > default.
cat > "$CONFIG" <<EOF
# vibe-tla machine settings — written by install_tlc.sh ($(java -version 2>&1 | head -1))
TLA_TOOLS_JAR=$JAR
REPO_ROOT=$REPO_ROOT
WORKSPACE_DIR=$WORKSPACE_DIR
TLC_WORKERS=${CLI_TLC_WORKERS:-${TLC_WORKERS:-auto}}
TLC_TIMEOUT=${CLI_TLC_TIMEOUT:-${TLC_TIMEOUT:-1800}}
VIBE_TLA_EFFORT=${CLI_VIBE_TLA_EFFORT:-${VIBE_TLA_EFFORT:-medium}}
REPO_MODE=${CLI_REPO_MODE:-${REPO_MODE:-embedded}}
REPO_URL=${CLI_REPO_URL:-${REPO_URL:-}}
EOF

echo "Wrote $CONFIG"
echo "  TLA_TOOLS_JAR=$JAR"
echo "  REPO_ROOT=$REPO_ROOT"
java -version 2>&1 | head -1
