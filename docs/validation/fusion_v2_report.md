# Fusion V2 PC comparison — 2026-10-30

## Observed results

| Check | Result |
|---|---|
| Original unit/regression tests | 17 passed, including original 512 fusion combinations |
| New grouped-rule/integration scenarios | 16 passed; feature/fault scenarios, not image accuracy |
| Original normal/fatigue video regression | 294 decision rows; all 19 original columns equal |
| Public full-pipeline comparison | YawDD first participant; 2741 source frames; 663 decision feature records over 88.27 s after the first decision |
| Warmed original LR | 260 valid decision records |
| Legacy observed distribution | L0=69, L1=152, L2=0, L3=442 |
| V2 observed distribution | L0=327, L1=39, L2=232, L3=65 |
| Different Legacy/V2 levels | 511/663; NOT an error rate |
| Level transition counts | Legacy 11, V2 22; V2 is NOT demonstrated more stable |
| Conflict decision records | 319; not a ground-truth count of model errors |
| Actual HTTP/WS control | Refuses closed gate, applies V2 and Legacy on new decisions, rejects invalid modes |

The comparison performs real Pose Transformer, FaceMesh, original LR and ONNX
ROI inference, then replays their logged actual inputs through the final pure V2
engine. It does not fabricate model outputs or train a fusion model. Per-decision
comparison and reason CSV: [fusion_v2_yawdd.csv](fusion_v2_yawdd.csv).
Policy, hash, metric counts and test exit codes: [fusion_v2_report.json](fusion_v2_report.json).
Original model inference journal remains local at `runs/fusion_v2_yawdd.jsonl`.
Underlying video is the same public YawDD sample already used by PC validation.
Original local clips are used only for the explicitly requested Legacy regression,
not as public benchmark data.

The pure rule replay median is approximately 0.027 ms, p95 0.055 ms in the recorded
run; exact host-dependent measurements are in JSON. In a bounded full camera-source
profile, peak RSS was approximately 462 MiB for Legacy and 503 MiB for active V2.
These include decode/Pose/Transformer/FaceMesh/fusion/JPEG, exclude HTTP/browser,
and use OMP/MKL threads=1 in both subprocesses. Different amounts of source video
were processed, so these are resource observations, not an equal-workload speedup.
The entire pipeline is NOT accepted as real-time. See
[fusion_desktop_resources.json](fusion_desktop_resources.json).

## Scenario coverage and boundaries

New unit cases cover normal/short closure, consensus long closure, left/right
asymmetry, EAR/YOLO conflict, MAR/YOLO conflict, short mouth opening, sustained
yawn capped at L1, partial/full YOLO loss, face loss, past/future timestamps,
LR warmup, correlated features not double counted, independent evidence escalation,
brief head/turn/forward feature surrogates, Pose/head disagreement, sustained
head/Pose support, upgrades, downgrades and persistence. They do not establish
natural-video recognition performance for these named behaviors.

This YawDD sequence has no reliable per-frame risk/speech/laughter/singing labels.
False-positive rate, false-negative rate and detection delay are explicitly NULL
in JSON. Neither different levels nor fewer L3 decisions demonstrate improvement.
Natural-video L2 ground truth and labelled fatigue nod/instrument-glance/turning/
forward-motion discrimination remain unvalidated. The binary Transformer cannot
reliably assign all those semantic categories without further evidence.

The first/last sampled smile and mouth-opening intervals documented in the
previous public-data qualitative review remain observations, not error-rate
measurements. Night NITYMED data requires an access request and was not obtained.
Public checkpoint licensing is still unconfirmed; model files are not committed.

## Release decision

The implementation passes basic structural, fallback, source-hash/policy gate and
integration checks. It is suitable for explicit PC trial and comparison only.
Legacy remains the default. V2 requires both operator opt-in and a matching
passing report. The report's `basic_acceptance_passed` does not mean higher
accuracy, improved stability, calibrated confidence or production readiness.
No RK3568/RKNN/NPU/INT8 actions were performed in this phase.
