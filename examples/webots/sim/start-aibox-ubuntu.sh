#!/usr/bin/env bash
# SPDX-License-Identifier: MulanPSL-2.0
# Start Webots with endpoints reachable by AIBOX over Tailscale.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "[sim/aibox-ubuntu] tailscale is required to resolve this host's Tailscale address" >&2
  exit 1
fi

TAILSCALE_IP="$(tailscale ip -4 | head -n1)"
if [[ -z "$TAILSCALE_IP" ]] || ! ip -o -4 addr show dev tailscale0 2>/dev/null \
    | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$TAILSCALE_IP"; then
  echo "[sim/aibox-ubuntu] no active IPv4 address found on tailscale0" >&2
  exit 1
fi

if [[ -n "${ROBONIX_ADVERTISE_HOST:-}" && "$ROBONIX_ADVERTISE_HOST" != "$TAILSCALE_IP" ]]; then
  printf "[sim/aibox-ubuntu] ROBONIX_ADVERTISE_HOST must match this host\x27s Tailscale address (%s)\n" "$TAILSCALE_IP" >&2
  exit 2
fi

export ROBONIX_SIM_NETWORK=host
export ROBONIX_ADVERTISE_HOST="$TAILSCALE_IP"
export ROBONIX_SIM_ZENOH_PORT="${ROBONIX_SIM_ZENOH_PORT:-7447}"
export ROBONIX_ZENOH_COMPRESSION="${ROBONIX_ZENOH_COMPRESSION:-1}"

echo "[sim/aibox-ubuntu] using host networking; dynamic provider ports are reachable on $TAILSCALE_IP"
echo "[sim/aibox-ubuntu] AIBOX Zenoh connects directly to tcp/$TAILSCALE_IP:$ROBONIX_SIM_ZENOH_PORT"
exec bash "$SCRIPT_DIR/start.sh" "$@"
