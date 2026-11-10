#!/usr/bin/env bash
#
# Resume-Matcher launcher — called by the .app wrapper.
#
# Arg: "start" | "stop" | "open"
#
# start: ensure Docker is up, ensure image exists, start the stack, wait,
#        print "READY" when the frontend answers.
# stop:  bring the stack down.
# open:  open the app URL in the default browser.

set -u

REPO="/Users/divya/Projects/Resume-Matcher"
APP_URL="http://localhost:3000"
IMAGE_TAG="resume-matcher-local:latest"
LAUNCH_LOG="$HOME/Library/Logs/resume-matcher-launcher.log"
BRIDGE_PORT="11435"
BRIDGE_PID_FILE="$HOME/Library/Caches/resume-matcher-bridge.pid"
BRIDGE_LOG="$HOME/Library/Logs/resume-matcher-bridge.log"
BRIDGE_SCRIPT="$REPO/.app-launcher/claude-bridge.py"

mkdir -p "$(dirname "$LAUNCH_LOG")"

log() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >> "$LAUNCH_LOG"; }

cmd="${1:-start}"

case "$cmd" in
  open)
    # Plain `open "$APP_URL"` reuses an existing tab silently if the URL is
    # already loaded somewhere in the default browser — the user sees
    # nothing happen. `open location` via osascript goes through
    # LaunchServices with activation, so the browser is guaranteed to come
    # to the front whether or not a matching tab is already open.
    osascript -e "open location \"$APP_URL\"" >/dev/null 2>&1 || open "$APP_URL"
    # Belt and braces: explicitly activate the default HTTP browser
    # (Chrome specifically does not always come forward from
    # `open location` when its window is minimized or on another Space).
    # Uses python3 to parse LaunchServices preferences — BSD awk on macOS
    # can't do regex captures, so staying away from awk here.
    default_browser_bundle="$(python3 -c "
import plistlib, os, sys
try:
    with open(os.path.expanduser('~/Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist'), 'rb') as f:
        p = plistlib.load(f)
    for h in p.get('LSHandlers', []):
        if h.get('LSHandlerURLScheme') == 'http':
            print(h.get('LSHandlerRoleAll', ''))
            break
except Exception:
    pass
" 2>/dev/null)"
    if [ -n "$default_browser_bundle" ]; then
      open -b "$default_browser_bundle" >/dev/null 2>&1 || true
    fi
    exit 0
    ;;

  stop)
    log "stop requested"
    cd "$REPO" || exit 1
    ./dev.sh stop >> "$LAUNCH_LOG" 2>&1
    # Tear down the Claude bridge too, if it was started by a previous run.
    if [ -f "$BRIDGE_PID_FILE" ]; then
      bpid="$(cat "$BRIDGE_PID_FILE" 2>/dev/null || true)"
      if [ -n "$bpid" ] && kill -0 "$bpid" 2>/dev/null; then
        kill "$bpid" 2>/dev/null || true
        log "bridge pid $bpid stopped"
      fi
      rm -f "$BRIDGE_PID_FILE"
    fi
    log "stopped"
    exit 0
    ;;

  bridge-status)
    if curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" >/dev/null 2>&1; then
      echo "up"
    else
      echo "down"
    fi
    exit 0
    ;;

  status)
    # Writes one word to stdout: docker_down | containers_down | up
    if ! docker info >/dev/null 2>&1; then
      echo "docker_down"; exit 0
    fi
    if ! docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "resume-matcher"; then
      echo "containers_down"; exit 0
    fi
    if curl -sfI "$APP_URL" >/dev/null 2>&1; then
      echo "up"
    else
      echo "containers_up_but_frontend_not_ready"
    fi
    exit 0
    ;;

  start)
    printf '\n========== %s start ==========\n' "$(date)" >> "$LAUNCH_LOG"
    cd "$REPO" || { log "repo missing at $REPO"; echo "ERR: repo missing"; exit 1; }

    # Docker Desktop
    # Note on quirks:
    #  - `open -g` can silently no-op right after a quit while launchd still
    #    has Docker marked as running, so this uses plain `open -a`.
    #  - Docker Desktop's GUI can be present while its daemon socket is still
    #    coming up for 20–40 s, so we poll `docker info` until it answers.
    if ! docker info >/dev/null 2>&1; then
      log "docker not running — launching Docker Desktop"
      if ! open -a "Docker" 2>>"$LAUNCH_LOG"; then
        if [ -d "/Applications/Docker.app" ]; then
          open "/Applications/Docker.app" 2>>"$LAUNCH_LOG" || true
        else
          log "Docker.app not found in /Applications"
          echo "ERR: Docker Desktop is not installed at /Applications/Docker.app"
          exit 1
        fi
      fi
      for i in $(seq 1 300); do
        if docker info >/dev/null 2>&1; then log "docker up after ${i}s"; break; fi
        sleep 1
      done
      if ! docker info >/dev/null 2>&1; then
        log "docker timed out"; echo "ERR: Docker did not start in 5 min"; exit 1
      fi
    fi

    # First-run image build
    if ! docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
      log "building $IMAGE_TAG (first run)"
      docker compose build >> "$LAUNCH_LOG" 2>&1 || { log "build failed"; echo "ERR: docker compose build failed (see log)"; exit 1; }
    fi

    # Claude bridge (host-side shim so the backend can reach the user's
    # `claude` CLI from inside the Docker container). Skipped silently if
    # Python 3 or FastAPI aren't available — the main app still works with
    # the other providers; only the Claude Code CLI option needs this.
    if ! curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" >/dev/null 2>&1; then
      if command -v python3 >/dev/null 2>&1 && python3 -c "import fastapi, uvicorn" 2>/dev/null; then
        log "starting Claude bridge on 127.0.0.1:${BRIDGE_PORT}"
        nohup python3 "$BRIDGE_SCRIPT" >> "$BRIDGE_LOG" 2>&1 &
        echo $! > "$BRIDGE_PID_FILE"
        for i in $(seq 1 10); do
          curl -sf "http://127.0.0.1:${BRIDGE_PORT}/health" >/dev/null 2>&1 && { log "bridge up after ${i}s"; break; }
          sleep 1
        done
      else
        log "skipping bridge: python3 + fastapi + uvicorn not available (pip install fastapi uvicorn to enable)"
      fi
    else
      log "Claude bridge already up"
    fi

    # Start stack
    log "starting dev stack"
    ./dev.sh -d >> "$LAUNCH_LOG" 2>&1

    # Wait for frontend
    log "waiting for $APP_URL"
    for i in $(seq 1 90); do
      if curl -sfI "$APP_URL" >/dev/null 2>&1; then
        log "frontend ready after ${i}s"
        echo "READY"
        exit 0
      fi
      sleep 1
    done
    log "frontend never came up"
    echo "ERR: frontend did not come up in 90s (see log)"
    exit 1
    ;;

  *)
    echo "usage: $0 {start|stop|open|status}" >&2
    exit 2
    ;;
esac
