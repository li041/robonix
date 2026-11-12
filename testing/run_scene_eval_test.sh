#!/bin/bash
# Scene evaluation test script for AIBOX NPU deployment
# This script guides through the full test workflow

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Scene Evaluation Test for AIBOX NPU ==="
echo ""

# Check prerequisites
echo "[1/7] Checking prerequisites..."
if ! command -v ssh &> /dev/null; then
    echo "ERROR: ssh not found"
    exit 1
fi

# Source the boot environment
cd "$REPO_ROOT/examples/webots-aibox"
source boot.env 2>/dev/null || true

BOARD_HOST="${BOARD_ATLAS%%:*}"  # Extract IP from BOARD_ATLAS
echo "Board address: $BOARD_HOST"
echo ""

# Step 1: Start Webots simulator (if not already running)
echo "[2/7] Webots simulator should be running on Ubuntu host"
echo "      If not running, execute on Ubuntu host:"
echo "      WEBOTS_GUI=1 bash examples/webots/sim/start.sh --world office.wbt"
echo "      Wait for: '[sim/start] live odom, RGB, and lidar data received'"
echo ""
read -p "Press Enter when simulator is ready (or Ctrl+C to abort)..."
echo ""

# Step 2: Boot the stack on AIBOX
echo "[3/7] Booting stack on AIBOX..."
echo "      SSH to board and run:"
echo "      cd /root/robonix/examples/webots-aibox"
echo "      rbnx boot -f robonix_manifest.yaml --no-update-check -v"
echo ""
echo "      Wait for:"
echo "      - [ OK ] mapping ACTIVE"
echo "      - [ OK ] nav2 ACTIVE"
echo "      - [ OK ] scene ACTIVE (~105s for NPU load)"
echo "      - [ OK ] explore INACTIVE"
echo ""
read -p "Press Enter when stack is booted (or Ctrl+C to abort)..."
echo ""

# Step 3: Verify scene is working
echo "[4/7] Verifying scene service..."
echo "      Check scene API:"
echo "      curl --noproxy '*' http://$BOARD_HOST:50107/api/state | jq '.objects | length'"
echo ""
echo "      Expected: 0 objects initially (before navigation)"
echo ""
read -p "Press Enter to continue..."
echo ""

# Step 4: Export ground truth (on Ubuntu host, not board)
echo "[5/7] Exporting ground truth (run on Ubuntu host)..."
echo "      cd /home/lxh/robonix"
echo "      python3 testing/export_webots_scene_truth.py --world-id office --output /tmp/office_truth.json"
echo ""
read -p "Press Enter when done..."
echo ""

# Step 5: Run the boustrophedon sweep
echo "[6/7] Running the office coverage sweep..."
echo "      On the board, execute:"
echo "      cd /root/robonix"
echo "      source /opt/ros/humble/setup.bash"
echo "      source run/webots-ubuntu.env"
echo "      export PYTHONPATH=/root/robonix/pylib/robonix-api:\${PYTHONPATH:-}"
echo "      python3 testing/scene_drive.py --waypoints-file testing/waypoints_office.json --out /tmp/scene-drive.json"
echo ""
echo "      This will:"
echo "      - Walk the hand-tuned office boustrophedon (16 waypoints, 1.3m lanes)"
echo "      - Send each waypoint through the navigate skill; Scene observes en route"
echo "      - Judge safety by the simulator's collision count"
echo ""
read -p "Press Enter to start the sweep (or Ctrl+C to abort)..."
echo ""

# Step 6: Evaluate results
echo "[7/7] Evaluating scene results..."
echo "      After coverage run completes, evaluate on Ubuntu host:"
echo "      cd /home/lxh/robonix"
echo "      python3 testing/evaluate_webots_scene.py --world-id office --scene-url http://$BOARD_HOST:50107/api/state"
echo ""
echo "      Or if you saved the state file:"
echo "      python3 testing/evaluate_webots_scene.py --world-id office --state-file /tmp/scene-state.json"
echo ""

# Summary
echo "=== Test Summary ==="
echo ""
echo "Key metrics to check:"
echo "- Number of objects detected: curl http://$BOARD_HOST:50107/api/state | jq '.objects | length'"
echo "- Coverage: check scene_drive.py output for succeeded/total waypoints"
echo "- Evaluation scores: precision, recall, F1, mean center error"
echo ""
echo "Compare with baseline (2026-10-19):"
echo "- 20 objects detected"
echo "- 11 matches with ground truth"
echo "- Mean center error: 0.313 m"
echo ""
echo "Good luck!"
