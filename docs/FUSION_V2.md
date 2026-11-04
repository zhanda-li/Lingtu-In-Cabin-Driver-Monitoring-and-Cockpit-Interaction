> 当前状态索引（2026-11-04）：Windows UI启动器默认V2，库/API未配置时默认Legacy；Linux启动器默认Legacy。V2已在RK3568运行，但实时证据有效性与整机性能仍按[部署状态](DEPLOYMENT_STATUS.md)分项验收。下文保留PC规则实现与原验证阶段的技术范围。

# Fusion V2 · PC experimental evidence fusion

## Architecture and preservation

`ui/cam.py` still computes the entire original Legacy decision first. Its legacy
CSV, class ordering, Transformer input/weights, FaceBranch feature vector and
`src/fuse.py` are retained. `src/fusion_session.py` then reads that decision and
real model observations and calls the independent `src/fusion_v2.py` rule engine.
Only an explicitly selected V2 replaces the selected State's `l_fused`. The
backend derives severity/voice alarm descriptions from the selected policy.
Camera overlay and CLI selected-level output follow the selected State too.
The original `src/fuse.py` remains the Legacy-only reference entry point;
`FUSION_MODE` applies to the camera source used by `ui/server.py` and `ui/cam.py`.

One Pose extractor, one existing FaceMesh and the two existing ROI classifiers
are used. No training, new model, feature replacement or RKNN/NPU work was done.
The original `nod` frequency definition is unchanged. No independent `nod_event`
or exact nod count is claimed; the UI labels the existing rate in events/minute.

## File manifest

New algorithm files: `src/fusion_v2.py`, `src/fusion_session.py`. New view files:
`ui/web/fusion-v2.js`, `ui/web/fusion-v2.css`. New tests/tools:
`tools/test_fusion_v2.py`, `evaluate_fusion_v2.py`, `regress_fusion_v2_legacy.py`,
`check_fusion_ui_structure.py`. The original WebSocket and resource tools are
extended, not duplicated. Existing config, camera/State/server and monitor/detail/
shared-socket code have narrowly scoped integration changes. README and the two
new guides explain operation; validation JSON/CSV and screenshots provide evidence.
Exact added/modified paths are in [fusion_v2_files.json](validation/fusion_v2_files.json).
Preexisting user README, heart-rate and recording edits remain unstaged.

## Inputs and rules

| Evidence | Actual project input | Rule / boundary |
|---|---|---|
| Eye | `ear`, `en_now` or the same `norm_by_time`, `perclos`, left/right open probabilities | Current normalized EAR, bilateral YOLO and persistence. Geometry/Yolo conflict or asymmetric eyes are marked; correlated signals are not summed. |
| Mouth | `mar`, `yawn_probability`, current continuous duration | Sustained MAR and available YOLO support; disagreements are marked. A mouth group alone is capped at L1. |
| Head | `pitch/yaw/roll`, directional `head_swing`, original `nod` | Brief down-glances do not create L3 in V2. Sustained directional head evidence plus sustained Transformer support is required. |
| Transformer | actual `probs[fatigue]`, current Pose validity/timestamp, class/Legacy pose level | Persistence of the existing fatigue posterior; alone capped at L2. Ordinary driver actions cannot be reliably semantically separated using this binary classifier without more labelled validation. |
| FaceBranch | actual `predict_proba` output, `l2`, `fb.full()`, gate, finite sample count | Original LR only votes when actually warm and valid. Eye and LR are correlated, so their maximum forms the eye family. |

After each group, V2 takes ordinal maxima, not a probability sum. Independent
sustained eye-family plus mouth evidence may support L2. Single blink or single
yawn cannot cause L3. Strong bilateral eye/geometry closure or sustained
head/Transformer agreement may cause L3. No calibrated overall probability is
defined: `confidence=null`, `confidence_kind=ordinal_rules_not_probability`.
Per-model confidence values are real, uncalibrated model outputs, not accuracy.

### Default policy sources (provisional combinations)

| Parameter | Default | Source |
|---|---:|---|
| normalized EAR closure | <0.80 | existing `face.BLINK_THR` |
| per-eye high-confidence threshold | 0.70 | established YOLO Shadow probability boundary |
| continuous closure evidence | 1.0 s | existing `face.CLOSE_EYE_SEC` |
| MAR / Yawn probability | >0.55 / >0.80 | existing MAR and Shadow thresholds |
| mouth persistence | 1.5 s | established Shadow duration |
| PERCLOS mild / moderate | 0.187 / 0.426 | existing `ui.state` severity defaults |
| relative downward motion | 10 degrees | existing directional `face.HEAD_DEG` |
| severe persistence | 3.0 s | existing Transformer window duration, 45/15 |
| entry / downgrade hold | 0.5 / 1.5 s | original `fuse.B2_ENTER_SEC/B2_EXIT_SEC` |
| YOLO max result age | 0.5 s | established Shadow expiry |

The new combinations and the use of window duration as severe persistence are
engineering policy, not empirically optimal or physiologically calibrated limits.
Named overrides are possible through `config.FUSION_V2_POLICY`. After a policy or
engine edit, regenerate the validation report: switching checks both source hash
and the complete policy against that report. Library/API defaults remain Legacy; the Windows UI launchers explicitly select V2.

## Missing data, fallback, and explanations

Each group has valid/confidence/timestamp/stale/warmup; runtime also reports
per-model backend and measured latency where available. Missing timestamps are
invalid, not stale. Out-of-range timestamps are stale. FaceMesh loss invalidates
ROI evidence even if a classification recently completed. LR warmup or invalid
feature vectors cannot vote. Partial YOLO failure leaves independent valid groups
available. If both YOLO groups are unavailable, V2 uses the exact Legacy level and
records the degradation. This intentionally inherits Legacy behavior and its
limitations; it is not evidence of a confirmed normal state. When all sources are
invalid, explanations explicitly report insufficient evidence.
An unexpected V2 integration exception also publishes/logs the Legacy level with
invalid new evidence and an explicit degradation reason, instead of stopping the
camera source. This fallback has a fault-injection unit test.

`risk_reasons` describes the SELECTED mode. Independent `v2_risk_reasons`,
`legacy_reasons`, `legacy_level`, `fusion_v2_level`, and `final_level` avoid mixing
the explanation for V2 with the selected Legacy risk. Every decision in comparison
mode is recorded in `DMS_FUSION_LOG` (default `runs/fusion_v2_<pid>.jsonl`).
Use a fresh path per video replay: evaluation rejects non-monotonic appended logs.

## Run and select modes

```powershell
cd D:\sdk_env_v1.12.1\dms_project
$py='D:\Anaconda3\envs\dms\python.exe'
$env:DMS_YOLO_SHADOW='1'
$env:DMS_YOLO_BACKEND='onnx'
$env:DMS_FUSION_COMPARE='1'
$env:FUSION_MODE='legacy'
& $py ui/server.py --source cam
```

For the library/API, Legacy is the default even with YOLO enabled; Windows UI launchers explicitly set V2. To explicitly allow V2 after the
matching basic report exists, restart with `DMS_FUSION_V2_ALLOWED=1`. The monitoring
detail page then displays a backend-confirmed mode selector. For startup selection
also set `FUSION_MODE=v2`. A missing/mismatched/failed report rejects V2 selection.
This gate checks basic implementation tests, NOT superior detection quality.

To return to Legacy, use the acknowledged selector or restart with
`FUSION_MODE=legacy`. Remove comparison and Shadow environment variables to restore
the original path and omit new optional fields. No original UI/hardware APIs were
removed; the app's existing speech/notification consumers receive selected State.

## WebSocket additions

Existing keys remain. Real camera State optionally adds:

- `fusion_v2`: mode, legacy_level, fusion_v2_level, final_level, trend, reasons,
  five evidence groups, conflicts, valid/invalid sources, degradation reasons,
  runtime metadata, recent events and both source/wall update times.
- `yolo`: left/right open and closed probabilities, states, Yawn/No-Yawn
  probabilities, validity, actual per-model latency, timestamp and stale.
- Existing `yolo_shadow` is preserved.

`{"type":"fusion_mode","mode":"v2"}` receives an actual
`fusion_mode` acknowledgment with `ok`, selected configuration and
`effective=next_decision`; UI only changes the displayed active mode after a new
matching decision arrives. Closed gates, unsupported sources and invalid mode
values return `ok=false`. Comparison is source-specific; demo/CSV sources do not
manufacture model evidence. `State` is published only after all optional fields
are complete, preventing a half-built decision reaching the socket.

## Reproduce tests

```powershell
& $py tools/test_yolo_shadow.py          # original 17, including 512 original combinations
& $py tools/test_fusion_v2.py            # 16 grouped-rule/integration scenarios
& $py tools/regress_fusion_v2_legacy.py  # original 294 real decisions
# Existing public YawDD replay; synchronous inference for deterministic evidence:
$env:DMS_YOLO_ASYNC='0'
$env:DMS_FUSION_LOG='runs/fusion_v2_yawdd_fresh.jsonl'
& $py ui/cam.py --replay datasets/yawdd_samples/01-FemaleNoGlasses.avi --fast --no-overlay --dump runs/fusion_legacy.csv
& $py tools/evaluate_fusion_v2.py --log runs/fusion_v2_yawdd_fresh.jsonl
& $py tools/check_yolo_websocket.py --fusion-tests
& $py tools/check_fusion_ui_structure.py
& $py tools/profile_yolo_desktop.py --seconds 20 --fusion
```

See [actual comparison report](validation/fusion_v2_report.md) and
[UI preservation/testing](UI_V2.md). No RK3568, RKNN, NPU or INT8 conversion or
deployment is included. Future board work must separately validate dependencies,
converted model parity, driver compatibility, latency, memory and thermal behavior.
