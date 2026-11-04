> 最新显示与运行状态见[部署状态](DEPLOYMENT_STATUS.md)：RK3568已完成X11逻辑1280×800、Goodix触摸确认及重启自动横屏验证。当前工作副本增加camera_runtime速率/结果年龄诊断；下文的原PC截图与结构检查维持其阶段范围。

# Incremental monitoring UI extension

The original product's theme, backgrounds, gradients, type scale, card styling,
navigation, four monitoring sections, voice controls and hardware entry points
are retained. `style.css`, `pages.css`, `chrome.js` and `app.js` are unchanged.

`monitor.html` appends one section AFTER the original fatigue/vital/behavior/history
sections inside the existing scroll area. It mounts `fusion-v2.js`, with narrowly
scoped `fusion-v2.css`. Original card, mtiles, note, border-radius, panel and ink
tokens are reused, including the user's light theme and existing risk accents.
`detail.html` only adds a small fusion-mode/status note under the existing main
risk readout; the original risk remains the visual center.

New cards show selected final risk and mode, comparison, current reasons, separate
eyes/probabilities/EAR/PERCLOS/closure duration, mouth/MAR/Yawn duration/conflicts,
head angles/original nod rate, five grouped evidence explanations, per-model
runtime and recent real events. No new model probability is presented as overall
fatigue probability. Unknown exact nod count/independent nod cycle stays unavailable.

The component observes the EXISTING `XQ.connect` WebSocket through local browser
events; it does not open another model connection. It never injects random or
static model results. Demo/CSV sources without actual V2 evidence display invalid/
waiting states. Per-eye classification and group geometry validity are distinct.
WARMUP, INVALID, CONFLICT and STALE are not rendered as normal eyes or mouth.
No fresh decision for 1.5 wall-clock seconds marks the new panel STALE, including
repeated transmission of an old State. Socket close immediately marks connection
failure and clears current evidence. Historical events remain historical.

The native mode selector is visible only when the backend says switching is
allowed. It sends a real command, waits for acknowledgment and for a matching
decision before showing active V2. It does not locally pretend that a mode changed.
Details expand with native `<details>`, avoiding a second framework or dummy buttons.
Local selectors have 44px touch targets; the new grid collapses to two/one columns
without changing the old responsive rules.

## Verification evidence

- `tools/check_fusion_ui_structure.py` verifies original monitor/detail markup is
  byte-equivalent after removing only the specified additive nodes, and original
  CSS/navigation/home code is unchanged. Result: [ui_structure.json](validation/ui_structure.json).
- Real browser session `lingtu-fusion-v2`, actual local backend and public video.
  At 1024×600 the original fatigue/vital/behavior/history rectangles were identical
  before/after: x=139.703125, width=866.1875; y positions 106.109375, 344.015625,
  543.203125, 907.875. No horizontal overflow in this paired measurement.
  1280×800 was also inspected; the extension is below the existing content.
- Browser JavaScript error checks returned no errors. Actual backend switch tests
  verify refusal, V2, return to Legacy and invalid command handling:
  [fusion_websocket.json](validation/fusion_websocket.json).
- Test servers use independent config with external agents, ASR/TTS, WeChat and
  serial hardware disabled. They do not load the user's private configuration or
  send messages to other people. Existing product integrations were not replaced.

Before/after screenshots and actual V2/disconnect views are in
`docs/validation/ui/`. Screenshots contain real replay observations; chart values
and clocks differ because capture times differ. This is design preservation QA,
not a claim of pixel identity for evolving data or physical 10.1-inch device testing.
Physical touch, microphone, speech output and hardware outputs were not exercised.

Start the existing UI using the commands in [FUSION_V2.md](FUSION_V2.md).

For double-click use, launch `ui/run_ui_fusion.bat`. It calls the unchanged
`run_ui.bat`, enables real ONNX YOLO and side-by-side comparison, and now selects
V2 at the user's explicit request. `run_ui.bat` uses the same V2 defaults unless
overridden; `run_ui_legacy.bat` explicitly restores the original Legacy-only path.
The matching-report gate remains enforced. On the driving-monitor page,
click connect camera, then the assistant's More link to monitoring details and
scroll to the new multi-model section. Restart an already-running server for the
launcher defaults to take effect; an allowed active session can also switch via WS.
