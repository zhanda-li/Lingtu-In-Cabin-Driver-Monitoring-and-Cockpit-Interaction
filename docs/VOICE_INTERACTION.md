# 小瑞收音、跳页与点歌修复（2026-10-30）

本次保留原页面布局、样式、语音打断和 DMS/Fusion V2。修复实际执行链路，不新增视觉检测模型，不做 RK3568 部署。

### 听到了但没有语音回复

用户报告后，只读检查当前服务：TTS 默认开启，流式识别与 3 秒断句正常，服务端尚无兜底播放请求。用用户原句独立调用当前对话接口，1.42 秒生成真实回复；晓伊合成该回复的开头成功，输出 28944 字节 MP3。这两项不等于确认用户浏览器实际播放成功，也未读取用户浏览器的静音缓存。

修复确定存在的反馈缺口：静音、后台页面和无文字时，XQ.speak 现在给出原因；麦克风状态区显示“回复未播放”及“小瑞”的实际回复。未播放的回执带 `played:false`，后端不再把它当作播放完成或开启追问窗口；旧版不带 played 的完成回执保持兼容。过期轮次和非持麦连接不能提交完成回执。

按用户恢复语音回复的要求，TTS 配置增加 `enable_revision=reply-audible-20261030`：重启服务并刷新页面后，在当前模式允许播报时恢复一次浏览器语音开关，随后仍保留用户手动静音。若已使用此版本后再次静音，请在“设置 → 语音播报”打开。**用户这次无声的具体浏览器原因尚未直接确认**；恢复开关后若仍无声，应依据界面原因继续排查输出设备、浏览器播放与兜底状态。

## 原因与修复

| 问题 | 本次处理 |
|---|---|
| `asr.prefer=browser` 是按键输入的偏好，却被常听引擎解释为优先 Whisper；流式模型也未下载 | 常听优先现有 sherpa 流式实现，失败仍退回 Whisper；支持独立 `asr.wake_prefer` |
| Whisper 整段完成才出字，叠加原先用户指定的 10 秒静音断句 | 本机安装现有代码支持的公开流式模型，真实中间文字由原 partial 协议输出；用户最新选择将两路断句配置同步为 3 秒 |
| 音乐等页面没有 wake 模块，跳页后常听中断 | 沿用同一标签页的 `xq.wake.want=on` 接续采集；主动停止仍保留 off；首次访问首页等页面不会因此自动开麦 |
| 模型未就绪就显示在听，开头可能被丢掉 | 等后端真实 ready 才进入 listening；断线明确显示重连，重连后重新注册 voice_start |
| 取消权限等待后，迟到的授权仍开启麦克风 | 使用采集轮次标记，迟到授权释放音轨 |
| ScriptProcessor 每约 256 ms 才回调 | 缓冲由 4096 改为 1024 样本，16 kHz 下约 64 ms；上行协议仍为每片 100 ms |
| 多媒体页绑定了原生播放器后，统一 playCalm 入口返回 native 拒绝执行 | 委托给页面原有 playTrack，等待真实 play Promise，再确认成功或失败 |
| 页面各自转发语音消息，其他页面缺消费者 | XQ.connect 统一转发；移除三处旧转发，防止重复执行 |

浏览器权限、静音和播放限制仍生效。未自动重启用户服务，未执行 Git push。

## 使用

关闭旧服务窗口，双击 `ui/run_ui.bat`，浏览器 Ctrl+F5。首次允许麦克风；在驾驶监测页确认显示在听，再说“你好小瑞，打开多媒体”或“你好小瑞，给我放个音乐”。会话内跳页会重新申请/恢复麦克风，文档切换期间存在短暂空档，不宣称无缝采集。

第一次播放可能需要点击一次原有播放按钮；这是浏览器自动播放策略。失败不会报告为成功。跨页音乐仍是原先的保存位置、重新播放机制，可能有短暂间隙。

本机模型：`models/sherpa/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30/`。下载包 132.6 MB，加载日志模型约 167.3 MB；这是原有 ASR 支持的预训练模型，不是 DMS 模型或 RKNN 转换。

其他机器使用项目原脚本：

```powershell
& D:\Anaconda3\envs\dms\python.exe ui\voice\fetch_models.py asr
```

[公开下载地址](https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30.tar.bz2)。模型目录已忽略，不提交大文件。上游包 README 指向原始模型，分发前仍需核对原始模型许可。

`ui/config.json` 的 `asr.wake_prefer` 可设 `stream` 或 `whisper`；不填写时 `prefer=browser` 的常听链路优先流式，`prefer=local` 保留优先 Whisper。按键输入自己的 browser/local 策略不变。

10 秒断句是旧需求。2026-10-30 用户明确选择停顿 3 秒，两份配置已同步设置 `asr.rule1_min_trailing_silence=3.0`、`asr.rule2_min_trailing_silence=3.0`、`asr.whisper_silence_s=3.0`。代码内未提供配置时的历史默认值仍为 10 秒。追问窗口 `follow_s` 与一句话的静音断句是不同参数，本次不修改。重启服务后生效；3 秒是静音等待，后续识别和动作执行仍需时间。

## 验证

```powershell
node tools\test_ui_voice.js
& D:\Anaconda3\envs\dms\python.exe tools\test_voice_stream.py
& D:\Anaconda3\envs\dms\python.exe tools\validate_voice_stream.py
& D:\Anaconda3\envs\dms\python.exe tools\test_yolo_shadow.py
& D:\Anaconda3\envs\dms\python.exe tools\test_fusion_v2.py
```

真实音频验证复用本地已有 `runs/wake_samples`，没有重新录音。详见 [验证报告](validation/voice_interaction_report.md)。

## 仍需验证

真人远场、噪声、音乐外放时的唤醒与识别；说话中较长停顿；全链路与摄像头/NPU争用资源。当前没有音箱回声消除实测，也没有准确率或真人漏字率结论。ScriptProcessor 仍是旧 API，浏览器主线程繁忙时的稳定性还需验证。

导航语音支持现有页面跳转和最近服务区流程；真实定位、地图 API 和路线引导依赖权限、网络及用户配置。本次隔离测试禁用地图密钥，没有验证真实目的地路线。单次按键输入仍保留原有实现，不等同于常听流式输入。
