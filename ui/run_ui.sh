#!/usr/bin/env bash
# Linux entry point. No install, services, disks or board configuration changes.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$ROOT"
MODE="${DMS_RUN_MODE:-legacy}"
if [[ "${1:-}" == "--mode" ]]; then
    MODE="${2:?--mode requires legacy, shadow or v2}"
    shift 2
fi
case "$MODE" in
    legacy)
        export FUSION_MODE=legacy DMS_YOLO_SHADOW=0 DMS_FUSION_COMPARE=0 DMS_FUSION_V2_ALLOWED=0 ;;
    shadow)
        export FUSION_MODE=legacy DMS_YOLO_SHADOW=1 DMS_FUSION_COMPARE=1 DMS_FUSION_V2_ALLOWED=0 ;;
    v2)
        export FUSION_MODE=v2 DMS_YOLO_SHADOW=1 DMS_FUSION_COMPARE=1 DMS_FUSION_V2_ALLOWED=1 ;;
    *) echo "Invalid mode: $MODE (legacy/shadow/v2)" >&2; exit 2 ;;
esac
export DMS_YOLO_BACKEND="${DMS_YOLO_BACKEND:-onnx}"
export PYTHONIOENCODING=utf-8
PYTHON="${DMS_PYTHON:-python3}"
LOG="${DMS_UI_LOG:-runs/ui_linux_$(date +%Y%m%d_%H%M%S).log}"
mkdir -p -- "$(dirname -- "$LOG")"
echo "Mode=$MODE; camera=${DMS_CAMERA_DEVICE:-0}; python=$PYTHON; log=$LOG"
# Existing server opens the camera only after its UI connect action.
# Server args after --mode are passed unchanged, e.g. --port or --source cam:clip.mp4.
"$PYTHON" -u ui/server.py --source cam "$@" 2>&1 | tee -a -- "$LOG"
