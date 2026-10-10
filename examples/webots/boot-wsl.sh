#!/usr/bin/env bash
# SPDX-License-Identifier: MulanPSL-2.0
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export ROBONIX_EXPLORE_SOURCE_PATH="${ROBONIX_EXPLORE_SOURCE_PATH:-$SCRIPT_DIR/rbnx-boot/cache/skill-explore-rbnx}"
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ROBONIX_SIM_NETWORK=bridge
export ROBONIX_SIM_CONTAINER="${ROBONIX_SIM_CONTAINER:-robonix_tiago_sim}"
export ROBONIX_ADVERTISE_HOST="${ROBONIX_ADVERTISE_HOST:-127.0.0.1}"
export ROBONIX_ATLAS_LISTEN="${ROBONIX_ATLAS_LISTEN:-0.0.0.0:50051}"
export ROBONIX_ATLAS="${ROBONIX_ATLAS:-$ROBONIX_ADVERTISE_HOST:${ROBONIX_ATLAS_LISTEN##*:}}"
DOCKER_HOST_IP="$(docker exec "${ROBONIX_SIM_CONTAINER:-robonix_tiago_sim}" \
    python3 -c 'import socket; print(socket.gethostbyname("host.docker.internal"))')"
export ROBONIX_SIM_ATLAS="${ROBONIX_SIM_ATLAS:-$DOCKER_HOST_IP:${ROBONIX_ATLAS##*:}}"
export ROBONIX_ZENOH_ROUTER="${ROBONIX_ZENOH_ROUTER:-tcp/$DOCKER_HOST_IP:7447}"
case "${ROBONIX_TIAGO_VARIANT:-lite}" in
    lite) SOMA_YAML="$SCRIPT_DIR/soma.yaml" ;;
    full) SOMA_YAML="$SCRIPT_DIR/soma.full.yaml" ;;
    *) echo "unsupported TIAGo variant: $ROBONIX_TIAGO_VARIANT" >&2; exit 2 ;;
esac
export ROBONIX_SOMA_ROBOT_YAML="${ROBONIX_SOMA_ROBOT_YAML:-$SOMA_YAML}"
export ROBONIX_SOMA_STAGE1_TIMEOUT_SECS="${ROBONIX_SOMA_STAGE1_TIMEOUT_SECS:-300}"
export SCENE_ACTIVATE_TIMEOUT_S="${SCENE_ACTIVATE_TIMEOUT_S:-240}"
exec rbnx boot -f "$SCRIPT_DIR/robonix_manifest.wsl.yaml" "$@"
