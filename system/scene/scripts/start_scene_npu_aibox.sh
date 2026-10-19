#!/usr/bin/env bash
# SPDX-License-Identifier: MulanPSL-2.0
# Native scene start on the AIBOX with DualMap RKNPU3 backends.
#
# Uses the validated fp16 yolo_world_v2s / mobilesam encoder / CLIP ViT-B/32
# images in /root/robonix/dualmap/model/npu.  The board's rknn3_toolkit_lite
# 1.0.4 must match the PC RKNN3 Toolkit that built the graphs.
set -euo pipefail

SCENE=/root/robonix/system/scene
DU=SCENE_DUALMAP_NPU_DIR=/root/robonix/dualmap/model/npu \
SCENE_DUALMAP_CLIP_WEIGHTS=/root/weights/clip/ViT-B-32.pt \
SCENE_DUALMAP_ROOT=/opt/dualmap \
SCENE_DUALMAP_CLASSES=/root/robonix/dualmap/config/class_list/scene_eval_classes.txt \
ROBONIX_SCENE_FORCE=native \
"$SCENE/scripts/start_native.sh" "$@"
