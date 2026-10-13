#!/usr/bin/env bash
# get_repo.sh — acquire and track the repo the skill works on when it is installed
# STANDALONE (user-global / an agent's skill library) with no owning project to detect.
# In an EMBEDDED install (<repo>/.claude/skills/vibe-tla/) you do not need this — the repo
# is the project that owns the .claude/.  Subcommands:
#
#   get_repo.sh use <git-url-or-local-path> [--branch B]
#       A URL  -> clone into $VIBE_TLA_HOME/repos/<name> (or ff-pull if already cloned),
#                 record it as the active repo (REPO_MODE=remote), print the clone path.
#       A local git dir -> use it in place (REPO_MODE=local), record active, print its path.
#   get_repo.sh refresh          ff-pull the active remote clone (used by sync/check).
#   get_repo.sh active           print the active REPO_ROOT (exit 1 if none is set).
#
# The active repo is recorded in $VIBE_TLA_HOME/active.env (default ~/.vibe-tla).  Only one
# active repo at a time; re-run `use` with another URL to switch.
set -uo pipefail
die(){ echo "get_repo.sh: $*" >&2; exit 2; }

HOME_DIR="${VIBE_TLA_HOME:-$HOME/.vibe-tla}"
REPOS="$HOME_DIR/repos"
ACTIVE="$HOME_DIR/active.env"

write_active(){ # <repo-root> <mode> [url]
  mkdir -p "$HOME_DIR"
  { echo "# vibe-tla active repo pointer (written by get_repo.sh)"
    echo "REPO_ROOT=$1"
    echo "REPO_MODE=$2"
    echo "REPO_URL=${3:-}"
  } > "$ACTIVE"
}

read_active_root(){
  [[ -f "$ACTIVE" ]] || return 1
  # shellcheck disable=SC1090
  ( source "$ACTIVE" 2>/dev/null; [[ -n "${REPO_ROOT:-}" ]] && printf '%s\n' "$REPO_ROOT" )
}

cmd="${1:-}"; shift || true
case "$cmd" in
  use)
    [[ $# -ge 1 ]] || die "usage: get_repo.sh use <git-url-or-local-path> [--branch <branch>]"
    TARGET="$1"; shift
    BRANCH=""
    while [[ $# -gt 0 ]]; do case "$1" in --branch) BRANCH="${2:-}"; shift 2;; *) die "unknown arg: $1";; esac; done

    # Local git directory -> use in place, no clone.
    if [[ -d "$TARGET/.git" ]] || { [[ -d "$TARGET" ]] && git -C "$TARGET" rev-parse --is-inside-work-tree >/dev/null 2>&1; }; then
      ROOT="$(cd "$TARGET" && pwd)"
      write_active "$ROOT" local ""
      echo "using local repo in place: $ROOT" >&2
      printf '%s\n' "$ROOT"
      exit 0
    fi

    # Otherwise treat as a git URL to clone/refresh.
    command -v git >/dev/null 2>&1 || die "git not found — needed to clone $TARGET"
    name="$(basename "$TARGET")"; name="${name%.git}"
    [[ -n "$name" ]] || die "could not derive a repo name from: $TARGET"
    DEST="$REPOS/$name"
    mkdir -p "$REPOS"
    if [[ -d "$DEST/.git" ]]; then
      echo "refreshing existing clone: $DEST" >&2
      git -C "$DEST" fetch --quiet --all --prune >&2 || echo "warn: fetch failed (offline?)" >&2
      [[ -n "$BRANCH" ]] && git -C "$DEST" checkout --quiet "$BRANCH" >&2 || true
      git -C "$DEST" pull --quiet --ff-only >&2 || echo "warn: 'pull --ff-only' failed (diverged/local edits?)" >&2
    else
      echo "cloning $TARGET -> $DEST" >&2
      if [[ -n "$BRANCH" ]]; then
        git clone --quiet --branch "$BRANCH" "$TARGET" "$DEST" >&2 || die "git clone failed for $TARGET"
      else
        git clone --quiet "$TARGET" "$DEST" >&2 || die "git clone failed for $TARGET"
      fi
    fi
    ROOT="$(cd "$DEST" && pwd)"
    write_active "$ROOT" remote "$TARGET"
    printf '%s\n' "$ROOT"
    ;;

  refresh)
    ROOT="$(read_active_root)" || die "no active repo — run 'get_repo.sh use <url>' (or '/vibe-tla init <url>') first"
    # shellcheck disable=SC1090
    source "$ACTIVE" 2>/dev/null || true
    if [[ "${REPO_MODE:-}" == "remote" && -d "$ROOT/.git" ]]; then
      echo "refreshing $ROOT" >&2
      git -C "$ROOT" fetch --quiet --all --prune >&2 || echo "warn: fetch failed (offline?)" >&2
      git -C "$ROOT" pull --quiet --ff-only >&2 || echo "warn: 'pull --ff-only' failed" >&2
    else
      echo "active repo is not a remote clone ($ROOT) — nothing to refresh" >&2
    fi
    printf '%s\n' "$ROOT"
    ;;

  active)
    ROOT="$(read_active_root)" || die "no active repo recorded ($ACTIVE) — run '/vibe-tla init <url>' first"
    printf '%s\n' "$ROOT"
    ;;

  *) die "usage: get_repo.sh <use|refresh|active> ...";;
esac
