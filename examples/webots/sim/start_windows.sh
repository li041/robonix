#!/usr/bin/env bash
# SPDX-License-Identifier: MulanPSL-2.0
# Run Webots on Windows while keeping ROS 2 and RViz2 in the sim container.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WINDOWS_ROOT="${ROBONIX_WINDOWS_WEBOTS_ROOT:-/mnt/d/RobonixWebots}"
if [[ ! -d "$WINDOWS_ROOT" ]]; then
    echo "[sim/windows] Windows runtime directory not found: $WINDOWS_ROOT" >&2
    echo "[sim/windows] Set ROBONIX_WINDOWS_WEBOTS_ROOT to its WSL mount path." >&2
    exit 1
fi
ROBONIX_WINDOWS_WEBOTS_ROOT="$(cd "$WINDOWS_ROOT" && pwd)"
export ROBONIX_WINDOWS_WEBOTS_ROOT
ROBONIX_WINDOWS_WEBOTS_PATH="$(wslpath -w "$ROBONIX_WINDOWS_WEBOTS_ROOT/shared")"
export ROBONIX_WINDOWS_WEBOTS_PATH
export ROBONIX_SIM_STATE_DIR="$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/linux"
source "$SCRIPT_DIR/runtime_state.sh"
robonix_sim_init_runtime_state

export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ROBONIX_SIM_NETWORK=bridge
export ROBONIX_WEBOTS_WORLD="${ROBONIX_WEBOTS_WORLD:-office.wbt}"
export ROBONIX_TIAGO_VARIANT="${ROBONIX_TIAGO_VARIANT:-lite}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --world|-w)
            [[ $# -ge 2 ]] || { echo "--world requires a value" >&2; exit 2; }
            export ROBONIX_WEBOTS_WORLD="$2"
            shift 2
            ;;
        --tiago-variant)
            [[ $# -ge 2 ]] || { echo "--tiago-variant requires a value" >&2; exit 2; }
            export ROBONIX_TIAGO_VARIANT="$2"
            shift 2
            ;;
        --help|-h)
            echo "Usage: $0 [--world WORLD.wbt] [--tiago-variant lite|full]"
            exit 0
            ;;
        *) echo "[sim/windows] unknown argument: $1" >&2; exit 2 ;;
    esac
done

case "$ROBONIX_TIAGO_VARIANT" in
    lite|full) ;;
    *) echo "[sim/windows] unsupported TIAGo variant: $ROBONIX_TIAGO_VARIANT (choose lite or full)" >&2; exit 2 ;;
esac

for required in \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/start-host.ps1" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/stop-host.ps1" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/verify_ros.py" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/container-entrypoint.sh" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/zenoh-router.json5" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/zenoh-session.json5"; do
    if [[ ! -f "$required" ]]; then
        echo "[sim/windows] required Windows Webots runtime file is missing: $required" >&2
        exit 1
    fi
done

mkdir -p "$ROBONIX_WINDOWS_WEBOTS_ROOT/logs"
export DISPLAY="${DISPLAY:-:0}"
export ROBONIX_HOST_XAUTH="${XAUTHORITY:-$HOME/.Xauthority}"

nohup powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$(wslpath -w "$ROBONIX_WINDOWS_WEBOTS_ROOT/start-host.ps1")" \
    >"$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/start-host.log" 2>&1 </dev/null &
echo "$!" > "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/host-launcher.pid"

DC=(docker compose --project-name "$ROBONIX_SIM_PROJECT"
    -f "$SCRIPT_DIR/compose.yaml"
    -f "$SCRIPT_DIR/compose.wslg.yaml"
    -f "$SCRIPT_DIR/compose.windows.yaml")
"${DC[@]}" up -d --no-build

docker cp "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/verify_ros.py" \
    "$ROBONIX_SIM_CONTAINER:/tmp/verify_windows_ros.py"

if [[ -f "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/ros-bridge.pid" ]]; then
    bridge_pid="$(cat "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/ros-bridge.pid")"
    bridge_args="$(ps -p "$bridge_pid" -o args= 2>/dev/null || true)"
    if [[ "$bridge_args" == *"$ROBONIX_WINDOWS_WEBOTS_ROOT"* ]]; then
        kill -- "-$bridge_pid" 2>/dev/null || true
    fi
fi
setsid bash "$SCRIPT_DIR/windows/start-ros-bridge.sh" \
    >"$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/ros-bridge.log" 2>&1 </dev/null &
echo "$!" > "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/ros-bridge.pid"

echo '[sim/windows] waiting for live odometry, RGB, and lidar data...'
ready=0
for _ in {1..60}; do
    bridge_pid="$(cat "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/ros-bridge.pid")"
    if ! kill -0 "$bridge_pid" 2>/dev/null; then
        tail -n 60 "$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/ros-bridge.log"
        exit 1
    fi
    if [[ "$(docker inspect -f '{{.State.Running}}' "$ROBONIX_SIM_CONTAINER")" != true ]]; then
        docker logs --tail 60 "$ROBONIX_SIM_CONTAINER"
        exit 1
    fi
    if docker exec "$ROBONIX_SIM_CONTAINER" bash -lc \
        'source /opt/ros/humble/setup.bash; python3 /tmp/verify_windows_ros.py --ready-only' \
        2>/dev/null; then
        ready=1
        break
    fi
    sleep 2
done
if [[ "$ready" != 1 ]]; then
    echo '[sim/windows] no live sensor data' >&2
    exit 1
fi
echo '[sim/windows] live odometry, RGB, and lidar data received'

rviz_pid="$(robonix_sim_read_rviz_pid "$ROBONIX_SIM_RVIZ_PID_FILE" 2>/dev/null || true)"
if [[ -z "$rviz_pid" ]] || ! robonix_sim_rviz_pid_matches "$rviz_pid" "$SCRIPT_DIR/start_rviz.sh"; then
    bash "$SCRIPT_DIR/start_rviz.sh" >"$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/rviz.log" 2>&1 &
    robonix_sim_record_rviz_pid "$!" "$ROBONIX_SIM_RVIZ_PID_FILE"
fi
echo '[sim/windows] Windows Webots, ROS 2, and RViz2 are ready'
exec tail -n 20 -F \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/ros-bridge.log" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/logs/rviz.log"
