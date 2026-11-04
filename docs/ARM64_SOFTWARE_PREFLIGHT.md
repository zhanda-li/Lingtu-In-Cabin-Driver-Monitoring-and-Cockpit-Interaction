> 阶段更新（2026-11-04）：本手册是部署前的软件工具与48包审计快照。后续已在Ubuntu24.04.4/Python3.12.3上安装并运行五模型；实际补齐8项依赖、数值及性能验收见[当前部署状态](DEPLOYMENT_STATUS.md)。以下“待板端验证”是原准备阶段记录，不替代后续实测。

# ARM64实机前软件准备与执行手册

日期：2026-11-01。硬件仍为K1-MINI V2.2，固件未批准。本轮仅PC本地软件准备；本文所有Linux/RK3568执行步骤均为未来操作说明，**待板端验证**。不包含固件下载、制卡、刷机、eMMC或Android操作。

## 本轮边界和文件

没有修改src、ui、config.py、原摄像头/音频/启动脚本、模型或疲劳规则；原有用户未提交修改保留。复用原PoseExtractor、FaceExtractor、load_infer_model、OnnxClassifier及ROI预处理，不另写算法。

新增工具：

| 文件 | 功能 |
|---|---|
| `tools/resolve_arm64_metadata.py` | 目标Python/glibc/ARM64 wheel与传递依赖元数据解析；仅获取索引、JSON、METADATA |
| `tools/probe_linux_environment.py` | 默认只读系统清单，不打开设备；可选只读工具查询 |
| `tools/portability_models.py` | 冻结真实输入、逐个加载原模型、保存独立CPU结果 |
| `tools/compare_portability.py` | 校验输入/权重/类别一致后进行逐数组数值比较 |
| `tools/portability_tolerances.json` | 可审计的工程数值容差，不是疲劳判决阈值 |
| `tools/test_arm64_preflight.py` | 标记/ABI/glibc/依赖冲突、只读探测及对拍拒绝错误的单元测试 |
| `constraints-arm64-py311.txt` / `constraints-arm64-py312.txt` | 各48包的目标元数据解析快照；仍未板端安装验证 |

证据在`docs/validation/arm64_metadata_py311.json`、`arm64_metadata_py312.json`、`portability_pc_repeat.json`及[本轮报告](validation/arm64_preflight_report.md)。现有requirements与公共constraints草案保留，目标快照引用公共约束并补齐传递包版本。

## 依赖审查结论

| 库 | Python 3.11 / Debian 12标准基线 | Python 3.12 / Ubuntu 24.04标准基线 | 剩余条件 |
|---|---|---|---|
| MediaPipe 1.0.1 | py3-none、manylinux_2_28_aarch64 | 同左 | Tasks实际导入、.task运行、CPU指令/共享库，待板端验证 |
| torch 2.14.0+cpu | cp311、manylinux_2_28_aarch64 | cp312、同平台下限 | 官方CPU wheel元数据已核验，不含CUDA；ELF及实际推理待板端验证 |
| ORT 1.23.2 | cp311、manylinux_2_27/2_28_aarch64 | cp312、同平台 | CPUExecutionProvider与原ONNX实际加载待板端验证 |
| OpenCV contrib 5.0.0.93 | cp37-abi3、manylinux2014/2_17 | 同左 | V4L2、解码、系统GL依赖待板端验证；不安装第二种cv2发行包 |
| sherpa-onnx 1.13.8 | cp311、manylinux2014_aarch64 | cp312、同平台 | 同版本core及实际ASR模型待板端验证 |
| sherpa-onnx-core 1.13.8 | py3-none、manylinux2014_aarch64 | 同左 | 已找到真实发布文件，原生库加载仍待板端验证 |
| aiohttp 3.14.3 | cp311 ARM64 wheel | cp312 ARM64 wheel | 本地服务、WS及事件循环待板端验证 |

两套标准基线的glibc为2.36/2.39；这里不是候选KICKPI固件的实测版本。所有wheel按目标标记而非Windows宿主标记筛选，检查Requires-Python、CPython ABI、架构和可接受manylinux下限。通用`linux_aarch64`标签未作为glibc已确认的证明。Python补丁版本使用3.11.0/3.12.0基线筛选，实际镜像仍须检测。

两套依赖图各48包，元数据约束均满足，未引入CUDA/NVIDIA/triton或第二个OpenCV。重要关系：MediaPipe→opencv-contrib/NumPy/absl/sounddevice/flatbuffers/matplotlib；ORT→NumPy/flatbuffers/protobuf/sympy；sherpa→严格同版本core；edge-tts→aiohttp>=3.8,<4；SciPy 1.15.3要求NumPy>=1.23.5,<2.5，与2.2.6相容。详细每条Requires-Dist及活动依赖保存在JSON中。

**两套快照不能混用：**Python 3.11选择contourpy 1.3.3、networkx 3.6.1；3.12选择1.4.0、3.7。它们不同于简单复制PC包清单，不能把“顶层版本相同”当作环境完全一致。

元数据解析采用有界回溯（每包最多12个稳定版本），只报告找到的一套满足约束的解，不保证穷尽所有解。每个wheel记录来源、发布SHA256和METADATA SHA256；CPU索引提供的元数据哈希已核对，PyPI元数据通过HTTPS读取并记录哈希，未伪称全部经索引哈希验证。**没有下载wheel本体、安装依赖或检查ELF依赖，因此不是安装成功证明。**

官方来源：[MediaPipe](https://pypi.org/project/mediapipe/1.0.1/#files)、[PyTorch CPU索引](https://download.pytorch.org/whl/cpu/torch/)、[ORT](https://pypi.org/project/onnxruntime/1.23.2/#files)、[OpenCV contrib](https://pypi.org/project/opencv-contrib-python/5.0.0.93/#files)、[sherpa-core](https://pypi.org/project/sherpa-onnx-core/1.13.8/#files)、[aiohttp](https://pypi.org/project/aiohttp/3.14.3/#files)。

## 1. PC复查依赖

在项目dms环境执行，下列脚本不安装包：

```text
python tools/resolve_arm64_metadata.py --python 3.12 --glibc 2.39 --out docs/validation/arm64_metadata_py312.json
python tools/resolve_arm64_metadata.py --python 3.11 --glibc 2.36 --out docs/validation/arm64_metadata_py311.json
```

默认联网只取包元数据并缓存到`runs/arm64_metadata_cache`；加`--offline`只读缓存，缓存缺失则失败。快照是本轮元数据记录，不由脚本自动覆盖更新；若未来重新解析产生版本变化，应审查后再更新快照。

获准进入真实Linux软件测试后，在隔离的项目环境中先解析、不安装（按实际Python选311/312）：

```bash
python -m pip install --dry-run --ignore-installed --only-binary=:all: \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  -r requirements-arm64.txt -c constraints-arm64-py312.txt \
  --report runs/arm64_pip_plan.json
```

这条pip命令本轮没有执行。安装前检查报告：48包依赖是否变化、torch是否+cpu、是否出现源码构建/CUDA/多种OpenCV；逐项对照审计JSON中的wheel文件名/来源/SHA256，实际pip若选择另一个发行文件，应另核对其METADATA。安装后还需`python -m pip check`及实际导入，不能用Windows跨平台pip参数冒充目标标记完整解析。系统PortAudio、libstdc++、OpenCV所需GL等不在Python元数据依赖图内，需按真实缺失库单独审查。本轮不安装系统包、播放器或训练环境；Whisper/numba/llvmlite仍属独立可选验证范围。

## 2. 未来Linux只读环境检查

```bash
python tools/probe_linux_environment.py --out runs/environment_arm64.json
# 可选：只读查询已安装的v4l2-ctl/aplay/arecord/xrandr；不自动安装。
python tools/probe_linux_environment.py --probe-tools --out runs/environment_arm64_tools.json
```

默认仅读取OS、Python ABI、CPU架构/特征、glibc、内存、V4L2 sysfs条目与权限、DRM/帧缓冲显示信息、ALSA清单及NPU节点/模块。不会打开摄像头、播放/录音、运行NPU或修改sysfs。可选工具查询可能以只读方式访问设备，但不配置设备或启动服务。无权限/无命令会写入报告，不使用sudo、不修改组或权限。NPU节点存在不等于可推理；本阶段不安装RKNN、不做转换。

PC已运行同一脚本，报告明确`host_is_linux=false`；这不是板端环境检测结果。不要把检测脚本发送到板卡执行，直到获得对应授权。

## 3. 固定输入与独立模型测试

本轮实际使用本地`normal_00.mp4`和原`runs/fatigue2/best.pt`，不录制新数据。可复现命令（运行前选择新的输出目录）：

```text
python tools/portability_models.py prepare --video data/raw/normal/normal_00.mp4 --checkpoint runs/fatigue2/best.pt --out runs/portability_bundle_final
python tools/portability_models.py run --bundle runs/portability_bundle_final --out runs/portability_pc_final_reference
```

prepare会复制五份原模型到包内，按15Hz冻结45帧原始BGR输入及严格递增时间戳；使用原Pose归一化和checkpoint均值/标准差冻结`1×45×132`输入；从实际FaceExtractor结果裁剪左右眼/嘴部，复用原预处理冻结YOLO `1×3×224×224`张量。若缺失完整有效Pose窗口、没有人脸或ROI无效，明确失败，不填零、不合成标签。

包内权重和输入按原始字节SHA256校验，包含源视频哈希、取帧索引、采样频率、checkpoint窗口和类别。算法源码哈希只统一CRLF/LF，以兼容Git跨系统检出，不放宽权重或输入校验。

可通过`run --only pose`、`--only face`、`--only transformer`、`--only eye`、`--only mouth`独立定位；`eye`同时测左右眼。输出分别包含：

- Pose：33×4关键点及有效帧mask。
- Face：原FaceExtractor暴露的点集、EAR/MAR/Pitch/Yaw/Roll及mask；没有另开第二套FaceMesh。该接口不输出全部478点，本测试不伪称比较了全部478点。
- Transformer：原checkpoint结构、原始logits和softmax，强制CPU，无训练。
- YOLO：原ONNX元数据和类别顺序、固定张量输出、原ROI重预处理输出；区分预处理误差与推理误差，明确CPUExecutionProvider。

独立子进程用于隔离模型加载失败和MediaPipe已知析构延迟；报告关闭/落盘后子进程退出，生产DMS代码不变。检查工作进程日志与返回码，不能仅看输出文件存在。默认不覆盖已有包或运行目录。

## 4. 未来PC/RK3568同输入对拍

获得板端测试授权后，复制相同项目版本、完整冻结包和PC参考输出，不重新解码视频或重新生成输入，不从“最新runs目录”重新猜选权重。板端执行：

```bash
python tools/portability_models.py run --bundle runs/portability_bundle_final --out runs/portability_arm64
python tools/compare_portability.py runs/portability_pc_final_reference runs/portability_arm64 \
  --out runs/portability_pc_arm64_comparison.json
```

manifest、模型哈希、类别顺序、窗口、数组形状/dtype及有效mask必须一致。浮点比较同时报告max/mean绝对误差及相对误差；分类额外检查top1。拒绝输出损坏、无穷值、缺失模式不同及全NaN“通过”。工程初始容差在JSON中明确保存：通常atol=1e-5/rtol=1e-4，Face暴露输出atol=1e-4。它们不是已在RK3568校准的容差，更不是疲劳阈值；超差先定位，不为追求通过而修改疲劳规则。

本轮完成的是两次独立PC CPU运行，所有输出数值一致。**PC/RK3568数值对拍仍待板端验证。**

## 5. Legacy → Shadow → Fusion V2 → Web UI

全部为待板端验证的逐级门槛，前一级失败就停止升级；NPU不是CPU阶段的前置条件。

| 阶段 | 入口与配置 | 验收要求 |
|---|---|---|
| 环境/模型 | 上述环境清单、依赖检查、五个独立模型及固定输入比较 | 无缺库/非法指令，资产一致，差异有报告 |
| Legacy离线 | 原`ui/cam.py --replay ... --fast --dump ...`，YOLO关闭、FUSION_MODE=legacy、COMPARE=0 | 真实帧/时间轴，LR warmup和数据缺失状态正常；用原CSV比较器核对旧字段 |
| Shadow离线 | 同输入，YOLO=1、BACKEND=onnx、FUSION_MODE=legacy、COMPARE=1、V2_ALLOWED=0 | YOLO为真实结果，过期/invalid明确；最终Legacy等级不受YOLO改变 |
| V2离线 | 同输入，YOLO=1、COMPARE=1、V2_ALLOWED=1、FUSION_MODE=v2 | 现有验收报告/源码哈希/策略检查通过；缺失降级、冲突、滞回与旧算法语义保持 |
| Web UI视频 | 复用`bash ui/run_ui.sh --mode ... --source cam:本地视频.mp4` | 原页面和WS字段、模型状态、模式确认、连接异常提示正确 |
| 摄像头与语音 | 复用既有脚本和环境变量，最后才点击原UI连接摄像头 | V4L2协商帧率/尺寸、音频设备错误可见、15Hz/45帧语义不变、长时资源可接受 |

可复制的Linux离线命令模板（当前不执行）：

```bash
env DMS_YOLO_SHADOW=0 DMS_FUSION_COMPARE=0 DMS_FUSION_V2_ALLOWED=0 FUSION_MODE=legacy \
  python ui/cam.py --replay data/raw/normal/normal_00.mp4 --fast --no-overlay --dump runs/arm_legacy.csv
env DMS_YOLO_SHADOW=1 DMS_YOLO_BACKEND=onnx DMS_FUSION_COMPARE=1 DMS_FUSION_V2_ALLOWED=0 FUSION_MODE=legacy \
  python ui/cam.py --replay data/raw/normal/normal_00.mp4 --fast --no-overlay --dump runs/arm_shadow.csv
python tools/cmp_cam_fuse.py runs/arm_legacy.csv runs/arm_shadow.csv
env DMS_YOLO_SHADOW=1 DMS_YOLO_BACKEND=onnx DMS_FUSION_COMPARE=1 DMS_FUSION_V2_ALLOWED=1 FUSION_MODE=v2 \
  python ui/cam.py --replay data/raw/normal/normal_00.mp4 --fast --no-overlay --dump runs/arm_v2.csv
```

环境变量名`DMS_YOLO_SHADOW`沿用现有代码；不是名为Shadow的第三种融合公式。V2仍须现有`docs/validation/fusion_v2_report.json`匹配策略和源码，不能自行伪造通过报告。CSV的精确对拍适合板端Legacy/Shadow同链路回归，PC与ARM64浮点差异另用本次数值工具定位；V2等级不同本身不代表更好。无可靠标签就记录等级、原因和延迟，不编误报率/漏报率。

## 6. 故障排查表

| 现象 | 先检查 | 处理原则 |
|---|---|---|
| No matching distribution | Python ABI、aarch64、glibc、对应311/312快照及索引 | 不把x86/Android wheel装到Linux，不强制源码构建 |
| resolver冲突/出现CUDA | CPU +cpu来源及每条Requires-Dist | 保留错误报告，禁止绕过依赖或换掉Transformer |
| 两种OpenCV冲突 | pip清单及公共constraints的阻止项 | 在隔离环境只选择contrib，不改现有PC环境 |
| libGL/libstdc++/PortAudio缺失 | 实际错误库名、只读ELF依赖检查 | 按目标系统单独准备，不自动sudo安装 |
| Illegal instruction | CPU flags、具体首次失败库和wheel | 停止升级，记录原始错误；ABI标签不保证指令兼容 |
| MediaPipe无检测/ROI invalid | 固定输入哈希、时间戳、有效mask和模型日志 | 不填正常状态，不调整疲劳阈值掩盖问题 |
| 哈希或源码不匹配 | 项目版本、完整包、是否重新生成/修改资产 | 复制一致版本，不手改manifest强行放行 |
| 浮点超差/top1变化 | 固定张量输出与ROI预处理输出分开看 | 保留max/mean误差及版本；判断是否靠近现有阈值，不盲目放宽容差 |
| V2拒绝启动 | 原验收JSON、policy_source_sha256、策略与允许开关 | 不绕过后端校验；先退回Legacy或Shadow |
| V4L2无法打开 | 设备身份、占用、权限、已协商格式 | 复用既有兼容层，不修改分区/设备树或使用chmod777 |
| 没声音/播放器退出非零 | DMS_AUDIO_PLAYER/DMS_TTS_COMMAND、设备及MP3支持 | 原status明确报错；不假定播放器或声卡存在 |
| 显示/NPU条目缺失 | 环境清单、权限及厂商BSP证据 | 不认定屏幕不兼容或NPU可用，不进入刷机/转换 |

实际板端验收表中，每一级的硬件、依赖安装、数值、时序、UI、CPU/内存/温度/帧率均填写“待板端验证”，直到得到对应实测证据。本轮PC数据不得替代这些签收项。
