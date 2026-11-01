# PC端跨平台兼容改造与ARM64移植草案

日期：2026-11-01。PC参考分支`feat/yolo-face-shadow`，基线提交`44d3751`。本轮只改采集、音频、启动及依赖准备代码；未连接RK3568、未下载固件或访问存储设备。Ubuntu/Debian候选的硬件兼容门槛仍见[K1-MINI原调查](K1_MINI_V22_IMAGE_AUDIT.md)。

## 设计边界

采用共享的摄像头选择函数及显式音频命令适配，保持CameraSource读帧/时间接口和ServerVoice对外API。分别在调用处硬编码Linux分支会重复配置；直接更换采集/语音框架则影响较大，因此本轮没有采用。平台选择不参与算法推理、时间采样或疲劳融合。

Windows默认DirectShow，Linux默认V4L2，其他系统默认CAP_ANY。默认后端打不开设备时释放句柄并尝试CAP_ANY；用户显式指定后端时失败即报告。CameraSource仍返回原始OpenCV BGR帧及成功标志，media_time仍从第一帧开始按墙钟计时。请求设备30fps不等于改变Transformer的15Hz采样或45帧窗口。

Linux音频不默认安装或选择任何播放器、声卡或离线音色。在线合成仍使用原Edge路径；播放音频和离线念文字分别使用用户提供的argv命令。配置缺失、可执行文件不存在、非零退出或超时都返回错误，保留主循环及现有语音status/WebSocket格式。Windows的WPF MediaPlayer和SAPI路径保留。

## 文件清单

修改：

- `src/live.py`：CameraSource接入选择层；CLI接受设备路径；Linux TTS失败不中断循环，Windows子进程失败不计为已播放。
- `src/fuse.py`：仅`--cam`参数解析支持路径，原融合公式未变。
- `ui/cam.py`：转发camera配置，原帧源和推理调度不变。
- `ui/tts.py`：Linux播放/本地念稿适配，保留Windows路径、队列和取消机制。
- `tools/test_yolo_shadow.py`：原AST保护仅豁免本轮允许的采集初始化、TTS工作函数、摄像头CLI参数和兼容层导入；其余原算法仍与历史提交比较。额外平台测试覆盖这些豁免接口。

新增：

- `src/capture_backend.py`、`src/audio_playback.py`。
- `ui/run_ui.sh`。
- `.gitattributes`：仅为该Linux启动脚本固定LF换行，避免Windows检出后产生CRLF。
- `requirements-arm64.txt`、`constraints-arm64.txt`。
- `tools/test_platform_compat.py`、`tools/check_platform_launcher.py`。
- `tools/check_pc_platform.py`、`tools/audit_arm64_dependencies.py`。
- 本文、`docs/validation/arm64_dependency_audit.json`和`docs/validation/pc_linux_compat_report.md`。

既有验证脚本重新生成了`docs/validation/legacy_regression.json`、`docs/validation/fusion_websocket.json`及`docs/yolo_websocket_check.json`。原README、hr文件及tools/record.py已有用户修改，本轮未编辑这些文件。未更改`ui/web`、`.bat`、模型权重、阈值、FEATURE_NAMES或Tasks API。

## 摄像头配置

环境变量优先于UI camera配置及调用参数：

| 环境变量 | UI JSON键（camera下） | 默认 |
|---|---|---|
| DMS_CAMERA_DEVICE | device | 0 |
| DMS_CAMERA_BACKEND | backend | platform |
| DMS_CAMERA_WIDTH / HEIGHT | size: [宽, 高] | 1280×720 |
| DMS_CAMERA_FPS | fps | 不额外设置，设备协商 |

backend可选`platform`、`auto`、`dshow`、`v4l2`。设备可用整数、数字字符串或`/dev/video2`、`/dev/v4l/by-id/...`。尺寸和fps必须是正数。属性设置是请求，不保证设备接受，板端必须读取协商值核对。视频回放走原VideoSource，不应用这些摄像头参数。

现有config可增量合入下列片段，但本轮没有修改实际config.json：

```json
{"camera": {"device": "/dev/video2", "backend": "v4l2", "size": [1280, 720], "fps": 30}}
```

PC默认仍双击`ui/run_ui.bat`，无需改配置。

## Linux音频配置

支持`tts.server.audio_player`、`tts.server.tts_command`、`tts.server.audio_device`；环境变量`DMS_AUDIO_PLAYER`、`DMS_TTS_COMMAND`、`DMS_AUDIO_DEVICE`优先。命令必须是JSON参数数组，不是shell命令字符串；不支持管道、重定向或`&&`。音频路径和文本作为单独参数传递，含空格或引号也不会执行为shell代码。

- 文件播放器必须包含`{file}`，并支持Edge生成的MP3格式。
- 本地语音命令必须包含`{text}`，负责合成并播放文字；只生成文件而不播放的命令不符合此接口。
- 可选`{device}`需同时配置audio_device，设备名称应由实际播放器/音频栈核对后填写。
- 播放器应在前台运行，到播放结束再退出，失败必须返回非零退出码；不使用会自行后台化的命令或多层启动包装。

例如，仅在已确认目标系统安装ffplay、且它能打开所需音频输出之后，可配置：

```bash
export DMS_AUDIO_PLAYER='["ffplay","-nodisp","-autoexit","-loglevel","error","{file}"]'
```

这是可选播放器配置示例，不代表K1-MINI已安装ffplay或默认声卡可用。本轮未安装播放器。离线TTS也不默认假设有中文合成引擎；需另外提供已验证的`DMS_TTS_COMMAND`。

语音失败通过原status的`error`、`detail`、`edge_error`报告；live.py的TTSWorker通过last_error及stderr报告。队列API保持非阻塞。Linux的旧`engine=sapi`配置名仍走本地适配入口，不能理解为Linux提供Windows SAPI。命令退出0只证明进程报告成功，不证明扬声器真实出声。

## Linux启动入口

以下为未来Linux软件环境就绪后的使用方法，本轮没有在板端执行：

```bash
# 激活预先准备的项目虚拟环境后，从项目根目录运行。
DMS_CAMERA_DEVICE=/dev/video2 bash ui/run_ui.sh --mode legacy
DMS_CAMERA_DEVICE=/dev/video2 bash ui/run_ui.sh --mode shadow
DMS_CAMERA_DEVICE=/dev/video2 bash ui/run_ui.sh --mode v2
```

`--mode`放在第一个参数位置；默认legacy。也可用`DMS_RUN_MODE`。三种模式分别是原版无YOLO、YOLO影子输出且最终Legacy、YOLO参与Fusion V2。V2仍受现有后端验收门槛约束，脚本不会绕过验证。Windows现有入口的默认V2选择不受此脚本影响。

`DMS_PYTHON`可指定解释器完整路径（不包含命令行参数）；`DMS_UI_LOG`可指定日志文件，默认`runs/ui_linux_日期_时间.log`。其余参数原样交给现有`ui/server.py`，例如`--port 8765`、`--source cam:本地视频.mp4`。默认不自动打开浏览器；在本机浏览器访问`http://127.0.0.1:8765`。摄像头仍需在原UI点击连接后才打开。脚本不自动开放公网监听、不修改服务或系统配置。

## ARM64依赖草案与真实依赖关系

两份新依赖文件独立于原requirements，不修改PC环境。`constraints-arm64.txt`不是ARM64锁文件或安装成功声明，Python目标优先使用镜像原生3.12/3.11，镜像实际版本仍待核对。版本基于本轮读取的PC包元数据，原始声明见`docs/validation/arm64_dependency_audit.json`。

已核实关系：

- MediaPipe 1.0.1依赖`absl-py~=2.3`、`sounddevice~=0.5`、`flatbuffers~=25.9`、NumPy、certifi、OpenCV contrib和matplotlib。
- OpenCV contrib 5.0.0.93在本项目Python范围要求NumPy>=2；2.2.6符合。禁止再装其他cv2发行包，constraints用不可满足的版本约束阻止意外引入。
- ORT 1.23.2依赖NumPy>=1.21.6、flatbuffers、protobuf、sympy、packaging、coloredlogs。
- sherpa-onnx 1.13.8依赖严格同版本`sherpa-onnx-core==1.13.8`。不能只看到顶层包就认定ASR可安装。
- edge-tts 7.3.1要求aiohttp>=3.8,<4，与3.14.3兼容；SciPy 1.15.3要求NumPy>=1.23.5,<2.5，与2.2.6兼容。
- 本机torch通用发行元数据含Linux CUDA依赖标记，不能直接作为ARM64 CPU wheel依赖依据。草案明确锁`2.14.0+cpu`并指定官方CPU索引，后续必须审查真实解析报告。

前期已核对核心库的ARM64候选wheel，详见原调查续查表；本轮未执行Linux安装或完整ARM64依赖解析。`sherpa-onnx-core`、全部传递依赖、PortAudio/cffi、OpenCV系统共享库和CPU指令兼容仍需目标环境验证。sounddevice还需要可用的PortAudio及实际音频输入设备；安装Python包不会自动建立声卡。

运行草案不包含Ultralytics训练/导出环境，也不包含可选Whisper及其numba/llvmlite/tiktoken依赖；原有Whisper代码保留，但使用该回退前需单独验证。离线数据分析/完整开发测试可能还需原开发依赖中的pandas、scikit-learn等。不要为了补这些包重新引入opencv-python。

获准的软件环境中，可先只解析，不安装：

```bash
python3 -m pip install --dry-run --only-binary=:all: \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  -r requirements-arm64.txt -c constraints-arm64.txt \
  --report runs/arm64_install_plan.json
```

本轮未执行该命令。应在真实Linux ARM64虚拟环境运行：Windows上的默认pip解析仍按Windows处理，不能当作板端依赖验证。检查报告是否只有一个OpenCV、torch为+cpu、无CUDA/NVIDIA训练栈、sherpa-core匹配、无源码构建回退，再决定安装。dry-run也可能联网下载元数据/发行包，不属于本轮已经完成的验证。

## 回归与板端验收

PC命令（使用项目dms解释器）：

```text
python -m unittest discover -v -s tools -p "test_*.py"
python tools/regress_fusion_v2_legacy.py
python tools/check_yolo_websocket.py
python tools/check_yolo_websocket.py --fusion-tests
python tools/audit_arm64_dependencies.py
python tools/check_pc_platform.py --camera --voice
python tools/check_platform_launcher.py --bash <bash可执行文件>
```

最后两项分别会短时打开PC摄像头/念一句话，以及用参数记录替身检查脚本；都不操作板卡。PC结果与证据见[本轮报告](validation/pc_linux_compat_report.md)。

板端验收需在固件、TF启动和硬件操作分别获准后进行，不能由本轮代码改造自动获得授权：

1. 核对实际aarch64/Python/glibc/内核与固件校验、屏幕显示触摸；独立确认恢复方案和TF/eMMC写入边界。
2. 在独立虚拟环境审查依赖解析，导入Tasks/PyTorch/ORT/OpenCV/sherpa；分别加载原.task、Transformer、LR、YOLO ONNX。
3. V4L2核对设备身份、实际分辨率/fps、BGR形状、掉线重连和长时采集；确认15Hz调度与45帧窗口未变。
4. 核对播放设备、MP3解码、中文TTS、超时/取消、拔掉音频设备时错误可见且DMS继续运行；再测麦克风及ASR。
5. 在同一视频和时间轴对拍Windows与ARM64输出，先Legacy，再Shadow，最后V2；记录误差及原模型数值差异，不能要求不同CPU浮点逐位相同。
6. 验证原UI、语音、导航和硬件接口，再测整链路CPU、内存、温度、FPS和长时稳定性。当前没有Linux/ARM64结果，也没有RKNN/NPU/INT8结论。
