#!/usr/bin/env bash
set -e
SIM_DIR="$(cd "$(dirname "$0")/.." && pwd)"
source "$SIM_DIR/windows/ros-env.sh"
export WEBOTS_SHARED_FOLDER="${ROBONIX_WINDOWS_WEBOTS_PATH:?set ROBONIX_WINDOWS_WEBOTS_PATH}:$ROOT/shared"
export ROBONIX_WEBOTS_WORLD_PATH
ROBONIX_WEBOTS_WORLD_PATH="$(python3 -m eaios_webots.world_variant "$ROS_ROOT/share/eaios_webots/worlds/${ROBONIX_WEBOTS_WORLD:-office.wbt}" --variant "${ROBONIX_TIAGO_VARIANT:-lite}")"
exec "$ROS_ROOT/bin/ros2" launch eaios_webots robot_launch.py use_sim_time:=true world:="${ROBONIX_WEBOTS_WORLD:-office.wbt}" robot:="${ROBONIX_WEBOTS_ROBOT:-tiago_webots.urdf}"
