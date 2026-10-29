# YOLO eye/mouth shadow implementation (2026-10-30)

## Audit and boundaries

Actual entry points are `src/fuse.py` (CLI) and `ui/cam.py` (aiohttp camera source).
Both reuse `face.FaceExtractor`. `src/live.py` is Pose-only and is deliberately unchanged.
Pose is 33 x 4 = 132 features; Transformer window is 45 at nominal 15 Hz.
Face LR FEATURE_NAMES remains `(perclos, brate, nod)`. Existing EAR/MAR, PERCLOS,
head_swing, nod, risk gates, hysteresis and L0-L3 formulas are unchanged.
The shadow code receives the existing pixel-coordinate dictionary AFTER geometric
features have been computed. It never writes back to original features or decisions.
No second FaceMesh, training, replacement weights, or additional controller.

## Files

Modified: `config.py`, `src/face.py`, `ui/cam.py`.
Added: `src/face_roi_yolo.py`, `requirements-yolo-shadow.txt`,
`tools/check_yolo_shadow.py`, `tools/test_yolo_shadow.py`,
`tools/validate_yolo_mrl.py`, this guide and JSON evidence in `docs/`.
Existing unrelated dirty files are excluded from the commit.

## Real public weights

- https://raw.githubusercontent.com/hongshenlv/Fatigue-Detection/master/Blink_detection/best.pt
- https://raw.githubusercontent.com/hongshenlv/Fatigue-Detection/master/Blink_detection/best_yawn.pt

Local paths: `models/yolo_shadow/best.pt` (2,968,513 bytes) and
`models/yolo_shadow/best_yawn.pt` (2,963,713 bytes).
Both loaded and executed, task **classify**, training and inference size **224**.
Actual eyes: 0 closed, 1 open; mouth: 0 no_yawn, 1 yawn.
SHA256, full checkpoint training arguments and CPU measurements: `yolo_shadow_cpu.json`.
Exact mapping avoids the upstream substring bug where `yawn` also matches `no_yawn`.
Upstream requirements omit Ultralytics; they include Torch 2.4.0, torchvision 0.19.0
and MediaPipe 0.10.14. Local tested Ultralytics: 8.4.163.
The upstream LICENSE URL returned 404; explicit code and checkpoint licensing has
NOT been established. Weights are local only, not committed or redistributed.
Ultralytics licensing must also be checked for the intended distribution:
https://www.ultralytics.com/license .

Backup release inspected:
https://github.com/AYMANE-SNOUSSI/driver-drowsiness-detection/releases
v1.0 describes detection classes eye_open, eye_closed, mouth_open. Mouth-open is
not a yawn classification probability; no substitute is silently installed.
Release API returned 403 rate limit. Backup weight loading was unnecessary because
both preferred models run successfully; backup names/input/license were not runtime verified.

## Install and run (PowerShell, desktop)

```powershell
cd D:\sdk_env_v1.12.1\dms_project
$py = 'D:\Anaconda3\envs\dms\python.exe'
& $py -m pip install -r requirements-yolo-shadow.txt
& $py tools/check_yolo_shadow.py
$env:DMS_YOLO_SHADOW = '1'
$env:DMS_YOLO_LOG = 'runs/yolo_shadow.jsonl'
& $py src/fuse.py --no-voice
# Start the existing UI normally under the same environment to add yolo_shadow
# to the existing camera state. UI rendering/layout remains intact.
$env:DMS_YOLO_SHADOW = '0'
# Restart the process to disable (the default).
& $py tools/test_yolo_shadow.py
& $py tools/validate_yolo_mrl.py
```

Model paths can be changed in the new YOLO-only config block. Missing dependency,
unrecognized names or loading errors warn and leave the original DMS operational.
Restart required for configuration changes. CLI auxiliary output uses JSONL;
UI exposes an optional `yolo_shadow` field under its existing state.

## Output and temporal semantics

Left/right use anatomical driver sides in an unmirrored input. Verify orientation
if a camera source mirrors frames before detection. Probabilities are uncalibrated
classification outputs, not detection confidences. EMA time constant .12 s;
both eye open probabilities below .3 start a bilateral closure. On release a
.05–.8 s closure is a blink; at .8 s emit long_closure once. Mouth probability
above .8 AND MAR above .55 continuously for 1.5 s emits yawn_candidate once.
These new shadow thresholds are provisional; no claim that they reliably exclude
all talking, laughter or singing. Each ROI has independent inference; invalid ROI
has null probability and invalid status/event, resets that evidence and never votes.
Gaps over .5 s/backwards timestamps reset temporal evidence. Eye and mouth duration
are zero when invalid/inactive. Inference latency and errors are included.

## Verification evidence and limitations

Seven unit tests passed: three ROI regions, bounds/missing ROI, missing face with no
inference, invalid/gaps, blink, long closure one-shot, MAR disagreement and sustained
yawn candidate, plus AST comparisons of original algorithms. These are synthetic
state/structure checks, NOT real-video behavioural accuracy tests.
Both real model loading and CPU forward tests passed. Warm synthetic 96x96 BGR
input resized by Ultralytics to 224, 10 iterations: eye median 7.15 ms / p95 8.86 ms,
mouth median 6.71 ms / p95 7.74 ms. Excludes FaceMesh, camera and whole-app overhead.
MRL local public images: participant-separated qualitative smoke samples in
`yolo_mrl_smoke.json`; no accuracy reported, no train/validation split used to train.
Model training provenance/possible overlap with MRL is unknown.

Outstanding: labelled open/closed and yawn/no-yawn evaluation, actual blink/long
closure video tests, YawDD talking/laughing/singing false positives, NITYMED night
validation, full original L0-L3 and enabled/disabled end-to-end video regression.
YawDD access documented at https://qualinet.github.io/databases/video/yawdd_a_yawning_detection_dataset/
(4.9 GB archive); it was not downloaded. MRL and NITYMED websites timed out during
inspection. Split future evaluation by participant/video, never neighboring frames.
Independent nod_event is optional and not implemented; original nod remains intact.
Executed `tools/regress_fuse.py --limit 1`: both child inference programs returned
success, but the legacy comparator raised `KeyError: 'glance'` because it still
hardcodes four classes while current config has two. This is a failed regression
test, not a pass. Existing generated logs were not treated as fresh test evidence.
Current inference is synchronous (three forwards per detected face); enabled mode
can reduce frame rate and thereby alter sampling even though formulas are unchanged.
No CPU/memory whole-app profiling or NPU performance claims are made.

## RK3568 deployment plan (not yet converted or board-tested)

Use a separate desktop/Linux conversion environment with official RKNN-Toolkit2:
https://github.com/airockchip/rknn-toolkit2 . Do not install the training environment
on RK3568. Export each classifier with Ultralytics `model.export(format='onnx',
imgsz=224, batch=1, dynamic=False, opset=12)` in a separate environment; export has
not been executed here. Inspect ONNX shapes and outputs first.
Match Ultralytics classify preprocessing exactly (BGR to RGB, resize/center crop,
normalization); determine whether outputs are logits or probabilities, and apply
softmax only once. Start with non-quantized RKNN, `target_platform='rk3568'`,
load ONNX/build/export using the version-matched toolkit examples. Compare identical
ROI tensors and class ordering on CPU/ONNX/RKNN before enabling the board backend.
For INT8, use a separate public-data calibration participant set, including IR and
glasses; compare probability error, class agreement and temporal events on held-out
participants. Never assume INT8 parity. Use matched Lite2/runtime and board driver.
Measure warm p50/p95 latency, RSS and CPU on the 4GB board with the existing UI.
The current module implements desktop CPU inference only; NPU/ONNX runtime adapters
and board CPU fallback remain work to do. Keep shadow disabled on board until tested.

## Git delivery and rollback

The requested remote main is one commit ahead of local main. Work is delivered on
an independent feature branch without force-pushing or changing original main.
After merging, rollback with `git revert <feature-commit-sha>`; this preserves history.
Do not reset/clean this dirty workspace. Weights and datasets are not in the commit.
