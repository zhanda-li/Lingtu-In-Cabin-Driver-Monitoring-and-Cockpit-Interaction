# PC 语音交互验证

日期：2026-10-30。环境：Windows，`D:\Anaconda3\envs\dms\python.exe`，独立 Chromium 浏览器会话 `lingtu-voice-fix`。

## 自动回归

- `tools/test_ui_voice.js`：4 组行为检查通过，覆盖原生播放器委托/失败回执、迟到授权取消、断线重注册/等待 ready、音乐失败与同页跳转。
- `tools/test_voice_stream.py`：4 项通过，覆盖 browser 偏好优先流式、流式不可用退化、显式 local、独立 wake_prefer。
- `tools/test_yolo_shadow.py`：原有 17 项通过（含原有 512 组合融合回归）。
- `tools/test_fusion_v2.py`：16 项通过。
- JS 语法、Python 编译和修改范围的空白检查通过。原始用户未提交文件未纳入本次提交。

## 实际模型回放

复用已有合成音频，100 ms PCM 片送入真实 StreamAsr，附加静音触发断句。没有真人逐帧标签，不计算准确率。

| 既有音频 | 实际最终文字 | 中间更新数 | 首次中间文字对应输入音频位置 |
|---|---|---:|---:|
| pos_music | 你好小瑞给我放个音乐 | 8 | 0.4 s |
| pos_goto_media | 你好小瑞打开多媒体 | 8 | 0.6 s |
| pos_goto_nav | 你好小瑞导航 | 6 | 0.5 s |
| pos_rest_stop | 你好小瑞我要去休息区 | 9 | 0.6 s |
| pos_affirm | 要的 | 2 | 0.6 s |

每段压缩回放的 CPU 处理总耗时约 2.01～2.64 s，包含附加静音。这不是用户端到端等待时间。上表的 0.4～0.6 s 是输入音频位置，不含浏览器采集、唤醒和网络等待。原始结果保存在本机 `runs/voice_stream_validation.json`。

## 真实浏览器及 WebSocket

隔离服务端口 8816，使用示例配置，禁用外部 AI、微信、串口、摄像头及 TTS 播放。浏览器使用虚拟麦克风，不采集真人。

1. 未做播放手势时，实际 playCalm 返回 `ok:false, why:blocked`；没有假装成功。
2. 点击原有播放按钮后，真实 playCalm 返回 `ok:true`，音乐 `playing:true`，位置从 0 增至约 1.01 s。
3. 实际语音模块初始进入 starting；服务端 ready 后进入 listening，真实 PCM 上行片数持续增加。
4. 从音乐页执行原有 go:navi 前端处理后，实际进入 `/nav.html`，采集恢复 listening。
5. 将既有 pos_goto_media 音频通过浏览器原 `_push`/PCM 编码/WebSocket 实时发送，真实 KWS 唤醒，收到多次 partial、heard“你好小瑞打开多媒体”、do `go:media`；页面实际进入 `/media.html`，收音恢复并累计 612 片。测试求值因页面真正导航而中断，随后检查目标页面验证结果。
6. 在多媒体页通过同一路径发送 pos_music，实际 heard“你好小瑞给我放个音乐”、do `music`；收到播放成功话术，真实音乐 playing:true，进度约 38.30 s。不是静态演示数据。

代码未修改 CSS、布局或原有 UI 组件，新增页面脚本和事件处理。未进行真人麦克风、真实地图路线、RK3568 或 NPU 测试。

测试服务日志在页面切换/取消请求时出现 Windows asyncio Proactor 的 `WinError 10054` 连接重置回调异常。本次跳页、重连与点歌仍成功，尚未单独定位该底层连接告警；不能据此声称后端零异常。浏览器自身运行错误列表为空。

## 模型可追溯性

公开模型包由原 fetch_models.py 下载成功。模型 SHA-256：

```text
encoder.int8.onnx 5ac51e27981bb4dab01bb9be4958453ba50c3b61c063ddda0eab23fd3671aa4f
decoder.onnx      06522ad63cec0fdf6809f4e1db9bb4f7d710c34582e3b35db62ac60eccafac7e
joiner.int8.onnx  b34584dc6f561089e1d747fedebb3765f2caa72c927ef54d7ca55e5ae40a814b
```

哈希是本机文件完整性记录，不代表上游签名或许可审查结果。

## 用户选择 3 秒断句后的验证

本地与示例配置的两条流式静音规则和 Whisper 静音参数均为 3.0 秒，追问窗口未修改。真实 StreamAsr 加载后确认参数为 3.0；回放既有 pos_music 音频，再追加静音 2.9 秒时触发 endpoint（文件尾部本身已有少量静音，不是 2.9 秒阈值）。Whisper 断句包装器使用替代本地引擎检查边界：连续有声后静音 2.9 秒不提交，3.0 秒提交；本次边界检查未运行 Whisper 模型推理。

## 无声回复补充验证

- 当前服务只读诊断：识别有效，3 秒断句；TTS default_on/server_ok 均 true，服务端 spoken/dropped 为 0，edge_error 为空。浏览器实际静音偏好未知。
- 用户原句“小芮小芮你好小蕊在干嘛呢”独立调用真实 Agent，使用默认 State 而非真人疲劳数据，后端 deepseek，1.42 秒返回非空回复，无 API 错误。不是该用户原来那一轮的历史回放。
- 真实 ServerVoice `_edge_mp3` 合成回复开头，晓伊音色输出 28944 字节 MP3；未自动播放到用户扬声器，不能证明实际输出设备正常。
- `node tools/test_ui_voice.js`：6 组通过，新增一次恢复播报、后续手动静音保留、静音/后台原因、未播放回执及完成回执轮次固定。
- `python tools/test_voice_stream.py`：8 项通过，新增直接编译生产 voice_spoken 分支的测试，验证未播放回 IDLE、完成才进入 FOLLOW、过期轮次拒绝、非持麦连接拒绝。Windows 受限沙箱的异步测试挂起，正常运行环境重跑通过（0.298 秒）；未将挂起算成通过。
- Python 编译和修改的 JS 语法检查通过。用户浏览器无声的确切原因尚未直接确认，需在重启刷新后验证实际播报。
