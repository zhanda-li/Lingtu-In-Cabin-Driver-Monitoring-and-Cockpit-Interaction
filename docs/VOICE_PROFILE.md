# 小瑞：活泼俏皮伙伴音色

2026-10-30 根据用户选择设置 `sprite-playful-v1`。浏览器优先选择 Xiaoyi（晓伊），日常语速 1.06、音高 1.06；关心、严肃、警示的浏览器参数保留原值。浏览器缺少该音色时，仍按原规则选择普通话 Natural 等可用音色，实际效果取决于浏览器，推荐 Microsoft Edge。

服务端备路使用 `zh-CN-XiaoyiNeural`、`+6%`、`+8Hz`。严重提醒仍沿用原有减速、降调修正。未改动语音打断、语音识别、硬件接口或 Fusion V2。

本机 edge-tts 7.2.8 合成请求真实返回 403；仅升级该包至 7.3.1 后，晓伊、晓晓两份联网试听均成功（40608 / 42048 字节）。这说明合成链路恢复，不代表已证明音色符合所有人的偏好。依赖固定在 `ui/requirements-tts.txt`，双击 `ui/install_tts.bat` 安装。在线服务仍可能变化或不可用，失败会记录 `edge_error` 并退回 Windows SAPI；离线声音不等同于晓伊。

`ui/config.json` 为本地私有配置，示例同步到 `ui/config.example.json`。首次收到新 `voice_profile` 的页面会一次性更新旧音色缓存，保留静音设置；之后仍尊重试音页的手动选择。

关闭原 UI 服务，重新双击 `ui/run_ui.bat`，浏览器 Ctrl+F5 刷新。打开 `http://127.0.0.1:8765/voice.html` 可检查实际音色和服务端错误。未自动重启用户正在使用的服务。

生成真实试听（需要联网，不自动播放、不启动摄像头或其他外部服务）：

```powershell
& D:\Anaconda3\envs\dms\python.exe tools\preview_voice.py
```

输出到 `runs/voice_previews/sprite_normal.mp3` 和 `sprite_alert.mp3`，不提交音频。此工具测试服务端合成，不能替代浏览器实际试听。

回退：将 TTS 的 voice、voice_profile、normal 参数和 server 音色参数恢复；本机旧 TTS 段保存在 `runs/voice_tts_before.json`。其他私有配置无需修改。Git 不包含本地配置和备份，也不上传密钥。
