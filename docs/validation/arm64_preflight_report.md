# ARM64软件准备阶段PC验证报告

日期：2026-11-01。基线`8776bb9`，分支`feat/yolo-face-shadow`。本轮未连接RK3568、未下载固件或wheel本体、未安装依赖、未操作存储设备。所有板端项目：**待板端验证**。

## 已完成

| 项目 | 本轮实际结果 | 证据 |
|---|---|---|
| Ubuntu标准基线元数据 | Python3.12/glibc2.39/aarch64，48包找到满足约束的解，无元数据获取错误 | `arm64_metadata_py312.json` |
| Debian标准基线元数据 | Python3.11/glibc2.36/aarch64，同样48包满足约束 | `arm64_metadata_py311.json` |
| CPU torch | 官方2.14.0+cpu的两种ABI可用，CPU METADATA哈希核对通过，无CUDA/NVIDIA/triton依赖 | 两份元数据JSON中的torch记录 |
| sherpa core | 1.13.8的manylinux2014_aarch64实际发布文件和METADATA已取得 | 同上 |
| 目标快照 | 新增两份完整48包constraints，沿用原公共版本及OpenCV单发行包限制 | 根目录`constraints-arm64-py311/312.txt` |
| 只读环境脚本 | PC执行成功，明确host_is_linux=false，不调用摄像头/音频/NPU | `runs/environment_pc.json` |
| 独立原模型测试 | 五类模型各两轮PC CPU加载/推理通过；Pose/Face各45帧有效 | `runs/portability_pc_final_reference/`、`runs/portability_pc_final_repeat/` |
| 同输入重复数值 | 两个独立PC进程组之间，各数组max_abs=0；有效mask及类别一致 | `portability_pc_repeat.json` |
| 回归 | 原55项＋本轮12项，共67项全部通过 | `runs/arm64_preflight_regression.txt` |
| 算法与UI保护 | src、ui、config.py、.gitattributes相对基线无差异 | `git diff --exit-code`检查 |

原55项包含Legacy组合、Shadow、Fusion V2、语音及导航合同测试。本轮新增覆盖目标Linux标记、CPython ABI/glibc/架构、extras、依赖回溯冲突、禁止拉取wheel/固件本体、数值漂移、NaN/invalid、形状/dtype、top1变化、文件损坏、manifest/路径校验、源码换行和默认只读检测。

上轮294次视频决策/19列零差异作为已知基线保留，本轮没有重复执行该完整视频对拍，不冒充新结果。没有重新运行浏览器视觉测试；本轮没有修改原UI文件。

## 固定输入和模型来源

使用既有本地`data/raw/normal/normal_00.mp4`，从1秒起按15Hz冻结45帧。Transformer为显式指定的原`runs/fatigue2/best.pt`，窗口45、输入132维；Pose/Face为原.task，YOLO为原best.onnx/best_yawn.onnx。输入包`runs/portability_bundle_final/`包含原始输入和五份原权重副本，文件总量约81.2MiB；视频帧、窗口及ROI均来自真实数据，没有新增录制、随机输入或标签。

模型worker复用原类和参数。Pose只在该独立worker中将资产目录指向包内已校验副本；原DMS配置文件和模型参数不变。Face输出为原接口暴露的点集及几何量，不宣称对比了全部478点。YOLO同时比较固定张量概率和ROI重新预处理后的概率，左眼/右眼分开使用真实输入。

每次运行校验输入、模型和算法源码身份；源码仅规范CRLF/LF，其他字节严格一致。最终版包在此规范确定后重新生成并完成两轮CPU验证。对拍工程容差明确存在工具JSON及结果中，不修改任何疲劳规则，也不声称已对RK3568校准。

## 依赖审查的具体边界

完整48包图来自各自目标wheel的PEP658 METADATA，不是套用Windows已安装包的依赖。所有包均记录发行文件及发布SHA256，但没有下载包体或验证该SHA256对应的本地wheel；CPU METADATA的索引SHA256已核对，PyPI元数据记录HTTPS来源和实际内容哈希。缓存支持离线复查。

Python3.11与3.12存在两项传递包版本差异：contourpy 1.3.3/1.4.0，networkx 3.6.1/3.7，所以新增分开的快照。NumPy2.2.6满足原OpenCV5及SciPy约束。已排除多种cv2发行包、CUDA和训练导出环境；未强行更换任何原模型。

元数据解不是安装成功证明。候选镜像实际Python补丁/glibc/内核、ARM指令、ELF共享库、PortAudio/声卡、V4L2、MediaPipe和sherpa实际ARM导入/推理均**待板端验证**。未校准误报率、漏报率、检测延迟或整链路FPS。

## 交付与下一步

执行命令、逐级门槛及故障排查表见[ARM64软件准备手册](../ARM64_SOFTWARE_PREFLIGHT.md)。只读检测和模型工具已经准备好，但当前不发送到板卡执行。先获得后续硬件/软件操作授权并补齐厂商证据，再依次进行依赖解析/导入、固定输入数值对拍、Legacy、Shadow、V2、Web UI和真实外设/长时性能验收。NPU仅列举信息，不安装RKNN或做转换。
