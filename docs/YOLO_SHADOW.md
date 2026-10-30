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

Modified: `config.py`, `src/face.py`, `ui/cam.py`, `ui/state.py`, `tools/regress_fuse.py`.
Added: `src/face_roi_yolo.py`, `requirements-yolo-shadow.txt`,
`tools/check_yolo_shadow.py`, `tools/test_yolo_shadow.py`,
`tools/validate_yolo_mrl.py`, this guide and JSON evidence in `docs/`.
Additional modules/tools: `src/yolo_runtime.py`, `tools/export_yolo_shadow.py`,
`tools/convert_yolo_rknn.py`, `tools/fetch_yawdd_samples.py`, `tools/validate_yolo_video.py`,
`requirements-yolo-runtime.txt`.
`tools/download_yolo_shadow.py` downloads/verifies the exact audited checkpoints by SHA256.
`tools/evaluate_yolo_mrl.py` performs labelled, participant-separated MRL subset evaluation.
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
& $py tools/download_yolo_shadow.py
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

Seventeen tests passed: three ROI regions, bounds/missing ROI, missing face with no
inference, invalid/gaps, blink, long closure one-shot, MAR disagreement and sustained
yawn candidate, plus AST comparisons of original algorithms. These are synthetic
state/structure checks, NOT real-video behavioural accuracy tests. Additional tests
cover disabled FaceExtractor output against the original code on identical landmark
observations, UI serialization/risk isolation, bounded async queue, exact ONNX
preprocessing, actual ONNX fallback when Lite2 is missing, and all four UI severity
levels compared with the original implementation while shadow events are present.
Fusion expressions from the original and current `fuse.py` are also executed on
512 combinations of levels, gates, face presence and rule activity, exercising
L0/L1/L2/L3 without modifying any fusion source. This is deterministic source-code
regression coverage; it is not natural-video coverage of every risk transition.
Both real model loading and CPU forward tests passed. Warm synthetic 96x96 BGR
input resized by Ultralytics to 224, 10 iterations: eye median 7.15 ms / p95 8.86 ms,
mouth median 6.71 ms / p95 7.74 ms. Excludes FaceMesh, camera and whole-app overhead.
MRL initial public-image qualitative smoke samples are in `yolo_mrl_smoke.json`.
Subsequent labelled subset evaluation is reported below; no training was performed.
Model training provenance/possible overlap with MRL is unknown.

Outstanding: full eye-ROI pipeline and labelled yawn/no-yawn evaluation, actual blink/long
closure video tests, YawDD talking/laughing/singing false positives, NITYMED night
validation, full original L0-L3 and enabled/disabled end-to-end video regression.
YawDD access documented at https://qualinet.github.io/databases/video/yawdd_a_yawning_detection_dataset/
(5.3 GB tar containing a RAR); bounded member download is supported by
`tools/fetch_yawdd_samples.py`. Split future evaluation by participant/video, never neighboring frames.
Independent nod_event is optional and not implemented; original nod remains intact.
Fixed legacy regression comparator's four-class assumption; it now uses configured
classes, fails on missing columns/nonfinite probabilities/empty logs. Re-executed
`tools/regress_fuse.py --limit 1`: A__A_00, 146 rows, maximum probability difference
0, zero level differences. This checks Pose-only `live.py` against `fuse.py --no-face`,
not full face/risk regression. Existing old logs are not fresh test evidence.
Default enabled-mode scheduling now uses a single daemon worker and one queued frame,
replacing queued stale frames. Models/FaceMesh are not duplicated. `sample_timestamp`
and `result_age_seconds` identify results; consumers must deduplicate events by sample
timestamp. Results older than .5 seconds or with lost face are invalid. Async replay
with `--fast` may legitimately skip most frames: use `DMS_YOLO_ASYNC=0` for deterministic
offline analysis. Logs deduplicate completed samples. This bounds queue memory but
CPU contention and the image copy still require whole-system board profiling.
Desktop full-camera-source profiling is reported below. No NPU performance claims are made.
Real camera-source regression was also executed on `normal_00.mp4`: YOLO-disabled
CLI fusion versus ONNX shadow-enabled UI camera source, 167 decision rows and all
19 original columns identical. Shadow completed 336 samples with no inference errors.
Concurrent replay log inference latency median 51.88 ms, p95 97.16 ms for three ROIs;
this is under concurrent CPU load and is not interchangeable with single-model timing.
Evidence: `yolo_runtime_regression.json`. This clip stays L0 and is shorter than the
full LR history; no claim of full L0-L3 coverage or board real-time performance.
Repeated the same original-vs-shadow camera comparison on `fatigue_00.mp4`:
127 decision rows, all 19 columns exactly equal, observed L0 and L3. This clip
also has genuine FaceMesh loss (121/299 detected), and the existing gate remains
closed for all 127 decisions. Thus it exercises high-risk/facial-loss isolation,
but not LR voting or L1/L2 transitions. Evidence: `yolo_fatigue_runtime_regression.json`.
NITYMED official access page https://datasets.esdalab.ece.uop.gr/elementor-65/
requires a name/email/purpose request form. It was read but not submitted, so no
nighttime data was obtained or validation claimed.

## Public YawDD qualitative replay completed

`tools/fetch_yawdd_samples.py` inspected the official tar directory and obtained
the first independent RAR4 compressed member using bounded HTTP ranges. First
single-connection attempt was stopped after confirming its process command; the
bounded eight-connection range retry completed. UnRAR verified/decompressed the
member; it was not necessary to download the whole archive.
Local video: `datasets/yawdd_samples/01-FemaleNoGlasses.avi`;
original member `YawDD dataset/Dash/Female/1-FemaleNoGlasses.avi`.
The video is 91.37 seconds, 2741 frames at approximately 30 fps. Visual contact-sheet
inspection confirms a driver in a daylight car scene with varying mouth/eye states.
Replay sampled every sixth frame (5 Hz), reached video end, and processed 457 frames
with a face on all 457. After requiring confirmed-open eyes before ending a blink,
latest outputs are 7 blink events, one yawn_candidate at 56.60 s,
zero long_closure events. These are predictions, NOT measured accuracy or ground truth.
No reliable per-frame labels were supplied; talking/laughing/singing false-positive
rates, sensitivity and night performance remain unmeasured. One participant is not
a generalization test. There was no training or random adjacent-frame data split.

The latest acceptance-run ONNX + FaceMesh process took 33.07 seconds to process
the video at sampled speed. FaceMesh + three ROI inference median 62.97 ms,
p95 77.63 ms; peak sampled RSS 174.73 MiB, process CPU time / wall time 1.04 cores.
Earlier runs were faster; these are observed host-load-sensitive measurements,
not fixed latency guarantees or directly comparable full-pipeline timings.
These exclude full Pose Transformer/UI and are desktop results, not RK3568 estimates.
Detailed predictions/resources: `yawdd_shadow_replay.json`;
download provenance: `yawdd_download.json`. No video/images are committed.

```powershell
& $py tools/fetch_yawdd_samples.py
$env:DMS_YOLO_BACKEND = 'onnx'
& $py tools/validate_yolo_video.py datasets/yawdd_samples/01-FemaleNoGlasses.avi
```

## Labelled MRL subset evaluation

The public dataset's bundled `annotation.txt` explicitly defines filename fields
and eye state 0=closed, 1=open. `tools/evaluate_yolo_mrl.py` uses this label rather
than inferred model names. Evaluation uses only subjects s0034–s0037, up to 50
evenly spaced images per class per participant; other subjects are excluded.
No random neighboring-frame split, training, threshold tuning or calibration.
The subset has 371 images: confusion matrix rows=true/cols=predicted, order
[closed,open], is `[[167,4],[11,189]]`; accuracy is 356/371 = 95.96% at open p>=.5.
This is a measured labelled-subset result, NOT full MRL, end-to-end FaceMesh ROI,
night-driving or unseen-person generalization accuracy. The checkpoint's original
training provenance is unknown, so overlap with these subjects cannot be ruled out.
Detailed predictions/partition: `yolo_mrl_labelled_eval.json`.

```powershell
& $py tools/evaluate_yolo_mrl.py
```

## Desktop acceptance and failure handling

The current desktop scope can be reproduced without a board:

```powershell
# Existing desktop dms environment, exact checkpoint hashes checked first.
& $py -m pip install -r requirements-yolo-validation.txt
& $py tools/validate_yolo_desktop.py
# Also starts two short-lived localhost servers and profiles full CamSource:
& $py tools/validate_yolo_desktop.py --full
```

`--full` needs permission to use localhost networking. On Windows a restricted
network sandbox can stall creation of the asyncio event loop before test code
starts; the initial sandboxed probe was stopped after verifying its process
command, then the same check passed outside that network restriction. Test servers
bind only 127.0.0.1, use temporary test config with external agents/ASR/TTS/WeChat
and serial hardware disabled, and are terminated by the test's cleanup block.
It does not load the user's private UI config or send messages to other people.

`tools/check_yolo_websocket.py` starts actual aiohttp servers with shadow off/on.
Cover/index pages return HTTP 200 in both modes. The 42 original state keys are
identical; the off payload has no shadow field, and the on payload carries a
completed ONNX shadow result. Evidence: `yolo_websocket_check.json`. Browser
rendering is not tested by this API-level check.

Async publication uses a lock plus generation counters. Face loss, invalid ROI
or a discontinuous source timestamp invalidates previous evidence immediately;
late results from previous generations cannot replace it. Invalid inference output
retains the complete null/invalid schema. A blink now requires both smoothed open
probabilities above .7 on release; returning only to the uncertain range is not
counted as a blink. These changes affect shadow events only.

`tools/review_yolo_mouth.py` summarizes contact-sheet-reviewed YawDD intervals.
At 0–3 s and 20–23 s, visible smiles/varying mouth poses generated no candidate;
at 54–58 s sustained opening generated the candidate at 56.60 s. Review did not
include audio or reliable speech/laughter/singing labels. These observations are
qualitative, not a measured false-positive rate. Evidence:
`yolo_mouth_qualitative_review.json`.

`tools/profile_yolo_desktop.py` sequentially runs the full camera source with
shadow off/on using the public video. It includes decode, Pose Transformer,
FaceMesh, fusion and JPEG, but excludes the HTTP server/browser and hardware.
Warm CPU measurements exclude the first 10 seconds; RSS is sampled every .25 s.
The two bounded wall-time runs reach different video positions, so their CPU
figures must not be interpreted as an optimization or equal-workload speedup.
Actual numbers are in `yolo_desktop_resources.json`. The acceptance manifest
`yolo_desktop_acceptance.json` records per-case exit codes and source hashes.
The latest full run passed all eight stages. Full camera-source peak RSS was
469.54 MiB with shadow off and 511.39 MiB with ONNX async shadow on. Warm process
CPU/wall ratios were 7.52 and 7.85 core equivalents respectively. Both runs were
CPU-heavy and processed less video time than wall time; this does not establish
real-time operation, camera performance or RK3568 suitability. The standalone
ROI-only figures above must not be substituted for these full-source results.

RK3568/NPU execution is deferred by the user's choice until the board is connected.
Remaining desktop evidence gaps are reliable talking/laughter/singing labels,
multi-participant mouth/night validation, natural-video L1/L2 and warmed-LR voting
regressions, and commercial checkpoint licensing. No accuracy is claimed for
unlabelled YawDD intervals or synthetic fusion cases.

## ONNX and RK3568 deployment (ONNX verified; RKNN not converted/board-tested)

Use a separate desktop/Linux conversion environment with official RKNN-Toolkit2:
https://github.com/airockchip/rknn-toolkit2 . Do not install the training environment
on RK3568. `tools/export_yolo_shadow.py` has exported both classifiers successfully,
opset 12, fixed [1,3,224,224] inputs and [1,2] probability outputs.
ONNX 1.23.0 and ONNX Runtime 1.23.2 were used. Six identical tensors per model
(one synthetic image and five MRL eye images) passed parity assertions; max absolute
errors: eyes 2.98e-7, mouth 1.10e-6. Mouth-on-eye samples check export numerics ONLY.
Evidence: `yolo_onnx_parity.json`. Artifacts stay local under `models/yolo_shadow/`.
Match Ultralytics classify preprocessing exactly (BGR to RGB, resize/center crop,
normalization); determine whether outputs are logits or probabilities, and apply
softmax only once. Start with non-quantized RKNN, `target_platform='rk3568'`,
load ONNX/build/export using the version-matched toolkit examples. Compare identical
ROI tensors and class ordering on CPU/ONNX/RKNN before enabling the board backend.
For INT8, use a separate public-data calibration participant set, including IR and
glasses; compare probability error, class agreement and temporal events on held-out
participants. Never assume INT8 parity. Use matched Lite2/runtime and board driver.
Measure warm p50/p95 latency, RSS and CPU on the 4GB board with the existing UI.
`src/yolo_runtime.py` now supplies torch-free ONNX CPU and opt-in Lite2 with CPU
fallback. Native ONNX preprocessing matches the tested Ultralytics/PIL preprocessing
(RGB, shortest-edge bilinear resize, center crop, divide by 255; mean 0/std 1).
NPU expects RGB uint8 NHWC with the converter's divide-by-255 normalization. It accepts
only finite normalized two-class outputs; it does not guess/duplicate softmax.
RKNN load/init/inference errors switch that model to ONNX CPU and expose a reason.
Only the missing-Lite2 fallback was desktop tested. Successful NPU inference is untested.
`tools/convert_yolo_rknn.py` targets RK3568 with FP conversion by default. INT8 requires
explicit `--calibration` list of preprocessed public ROIs from separate participants.
Execution here failed with `ModuleNotFoundError: rknn`; no RKNN files were fabricated.
Keep shadow disabled on board until output parity and resource usage are verified.

```powershell
# Desktop export and verification
& $py tools/export_yolo_shadow.py
& $py -m pip install -r requirements-yolo-runtime.txt
$env:DMS_YOLO_BACKEND = 'onnx'  # pt (default), onnx, or opt-in rknn
$env:DMS_YOLO_ASYNC = '1'     # bounded async worker (default)
$env:DMS_YOLO_SHADOW = '1'
& $py ui/server.py --source cam
# Separate Linux conversion environment with RKNN-Toolkit2 installed:
# python tools/convert_yolo_rknn.py models/yolo_shadow/best.onnx
# python tools/convert_yolo_rknn.py models/yolo_shadow/best_yawn.onnx
# Board after verified conversion: set DMS_YOLO_BACKEND=rknn
# Deploy .onnx plus matching .fp.rknn files; no Ultralytics/Torch needed by YOLO runtime.
```

UI state integration uses an optional `State.yolo_shadow` field. It is omitted from
JSON when disabled, and ignored by `derive()`. The original dict-assignment bug was
fixed and covered by the serialization regression test.

## Git delivery and rollback

The requested remote main is one commit ahead of local main. Work is delivered on
an independent feature branch without force-pushing or changing original main.
After merging, rollback with `git revert <feature-commit-sha>`; this preserves history.
Do not reset/clean this dirty workspace. Weights and datasets are not in the commit.
