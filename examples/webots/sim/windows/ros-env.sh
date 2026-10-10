#!/usr/bin/env bash
ROOT="${ROBONIX_WINDOWS_WEBOTS_ROOT:?set ROBONIX_WINDOWS_WEBOTS_ROOT}"
LINUX_ROOT="$ROOT/runtime/linux-root"
ROS_ROOT="$LINUX_ROOT/opt/ros/humble"
export PYTHONNOUSERSITE=1
export LD_LIBRARY_PATH="$LINUX_ROOT/lib/x86_64-linux-gnu:$LINUX_ROOT/usr/lib/x86_64-linux-gnu:$ROS_ROOT/lib:$ROS_ROOT/lib/x86_64-linux-gnu:$ROS_ROOT/opt/zenoh_cpp_vendor/lib:$ROS_ROOT/opt/rviz_ogre_vendor/lib:${LD_LIBRARY_PATH:-}"
export PYTHONPATH="$ROS_ROOT/local/lib/python3.10/dist-packages:$ROS_ROOT/lib/python3.10/site-packages:$LINUX_ROOT/usr/local/lib/python3.10/dist-packages:$LINUX_ROOT/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
export PATH="$ROS_ROOT/bin:/usr/bin:/bin"
export COLCON_CURRENT_PREFIX="$ROS_ROOT"
source "$ROS_ROOT/local_setup.bash"
export RMW_IMPLEMENTATION=rmw_zenoh_cpp
export ROS_LOG_DIR="$ROOT/logs/ros"
export ZENOH_SESSION_CONFIG_URI="$ROOT/runtime/zenoh-session.json5"
