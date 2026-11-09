#!/usr/bin/env bash
#
# dev.sh — start Resume-Matcher in dev mode with hot-reload.
#
# Iteration time per code change: ~1-2 seconds (backend .py) / ~200 ms
# (frontend .tsx via Turbopack HMR). Compare to ~5-10 minutes for a full
# `docker compose build` cycle. See docker-compose.dev.yml for the mechanics.
#
# Usage:
#   ./dev.sh                # start (foreground; Ctrl+C stops)
#   ./dev.sh -d             # start detached in background
#   ./dev.sh logs           # tail container logs
#   ./dev.sh stop           # stop the dev container
#   ./dev.sh reset          # remove container + re-run npm ci for a clean state
#
# First-time setup:
#   1. Build the production image once (bakes deps AND node_modules into
#      the image so dev mode has linux-arm64 node_modules available):
#        docker compose build
#   Host node_modules is NOT required — dev mode uses the image's own copy,
#   isolated inside an anonymous volume so it doesn't clash with a darwin
#   copy on the host.
#
# When to still `docker compose build`:
#   - Changed Dockerfile
#   - Added a Python dep in apps/backend/pyproject.toml
#   - Added a Node dep in apps/frontend/package.json (also re-run npm ci)
#   - Want to verify the final production build

set -euo pipefail

cd "$(dirname "$0")"

COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml)

cmd="${1:-up}"
case "$cmd" in
  up|start|"")
    # Preflight: warn if the two prereqs are missing.
    if ! docker image inspect resume-matcher-local:latest >/dev/null 2>&1; then
      echo "❌  No resume-matcher-local:latest image found." >&2
      echo "    Run once first:  docker compose build" >&2
      exit 1
    fi
    # No host-side node_modules check — dev mode uses the container's own
    # copy (populated by the image build) via an anonymous volume so the
    # host's darwin-arm64 build and the container's linux-arm64 build stay
    # cleanly separated.
    shift || true
    exec "${COMPOSE[@]}" up "$@"
    ;;

  -d)
    exec "${COMPOSE[@]}" up -d
    ;;

  logs)
    exec "${COMPOSE[@]}" logs -f
    ;;

  stop|down)
    exec "${COMPOSE[@]}" down
    ;;

  reset)
    "${COMPOSE[@]}" down -v || true
    echo "[dev] reinstalling frontend deps…"
    (cd apps/frontend && rm -rf node_modules && npm ci)
    echo "[dev] ready. Run:  ./dev.sh"
    ;;

  *)
    echo "Unknown command: $cmd" >&2
    echo "Usage: $0 [up|-d|logs|stop|reset]" >&2
    exit 1
    ;;
esac
