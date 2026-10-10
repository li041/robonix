#!/usr/bin/env bash
# SPDX-License-Identifier: MulanPSL-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
WINDOWS_ROOT="${ROBONIX_WINDOWS_WEBOTS_ROOT:-/mnt/d/RobonixWebots}"
ROBONIX_WINDOWS_WEBOTS_ROOT="$(cd "$WINDOWS_ROOT" && pwd)"
export ROBONIX_WINDOWS_WEBOTS_ROOT
export ROBONIX_SIM_STATE_DIR="$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/linux"
source "$SCRIPT_DIR/runtime_state.sh"
robonix_sim_init_runtime_state

bridge_pid_file="$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/ros-bridge.pid"
if [[ -f "$bridge_pid_file" ]]; then
    bridge_pid="$(cat "$bridge_pid_file")"
    bridge_args="$(ps -p "$bridge_pid" -o args= 2>/dev/null || true)"
    if [[ "$bridge_args" == *"$ROBONIX_WINDOWS_WEBOTS_ROOT"* ]]; then
        kill -- "-$bridge_pid" 2>/dev/null || true
    fi
fi

rviz_pid="$(robonix_sim_read_rviz_pid "$ROBONIX_SIM_RVIZ_PID_FILE" 2>/dev/null || true)"
if [[ -n "$rviz_pid" ]] && robonix_sim_rviz_pid_matches "$rviz_pid" "$SCRIPT_DIR/start_rviz.sh"; then
    kill "$rviz_pid" 2>/dev/null || true
fi

docker compose --project-name "$ROBONIX_SIM_PROJECT" \
    -f "$SCRIPT_DIR/compose.yaml" \
    -f "$SCRIPT_DIR/compose.wslg.yaml" \
    -f "$SCRIPT_DIR/compose.windows.yaml" down
powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass \
    -File "$(wslpath -w "$ROBONIX_WINDOWS_WEBOTS_ROOT/stop-host.ps1")"
rm -f "$ROBONIX_SIM_RVIZ_PID_FILE" \
    "$ROBONIX_WINDOWS_WEBOTS_ROOT/runtime/host-launcher.pid" \
    "$bridge_pid_file"
