# PC跨平台兼容性回归报告

日期：2026-11-01。执行环境为Windows / conda dms / Python 3.10.21。Linux实机和ARM64安装、推理均未测试。实现及配置见[使用说明](../PC_LINUX_COMPATIBILITY.md)。

## 基线与结果

Git分支`feat/yolo-face-shadow`，代码基线`44d3751`。开工时已有README、hr的三个文件及tools/record.py未提交修改，以及大量未跟踪文件；这些用户改动未被本轮编辑。没有reset、clean或push。

为排除当前改动影响，从HEAD导出原有Python代码到独立`runs/compat_baseline_*`目录，复制现有本地眼部/嘴部.pt和.onnx模型，运行原测试。未下载权重、固件或安装依赖。

| 检查 | 实际结果 | 证据 |
|---|---|---|
| 原代码快照 | 43项全部通过 | `runs/compat_windows_baseline.txt` |
| 修改后原测试＋兼容层测试 | 55项全部通过（新增12项） | `runs/compat_windows_after.txt` |
| 原融合组合 | 既有512种组合与原算法一致 | `test_yolo_shadow.test_all_fusion_levels_and_gates_against_original` |
| 本地视频对拍 | normal 167次、fatigue 127次，共294次，19列均零差异 | `docs/validation/legacy_regression.json` |
| YOLO关闭／开启 | HTTP首页和封面均200；WS旧字段一致，开启后真实ONNX结果可用 | `docs/yolo_websocket_check.json` |
| Legacy／V2 | 后端确认切换并反映到决策；禁止切换时拒绝请求 | `docs/validation/fusion_websocket.json` |
| Windows摄像头 | 实际DSHOW打开，读取BGR三通道，shape=[720,1280,3]；完成后释放 | `runs/compat_pc_hardware.json` |
| Windows语音 | 实际SAPI执行返回XQOK、spoken=1；没有用户听感确认 | 同上 |
| 算法导入 | MediaPipe Tasks的PoseLandmarker/FaceLandmarker、torch、ORT及现有算法模块导入通过 | 本轮PC命令输出；视频测试亦加载真实模型 |
| Linux启动脚本 | Git Bash语法、三模式环境变量、设备路径、参数、日志、非零退出码和非法模式拒绝通过 | `runs/compat_launcher.json` |
| 文件保护 | 259个受保护文件与HEAD比较无差异（仅归一化CRLF/LF） | `runs/compat_protected_files.json` |
| diff格式检查 | 本轮修改文件通过git diff --check | Git仅提示既有CRLF转换策略 |

保护文件范围包含ui/web、原.bat、已跟踪models、model.py、pose.py、face.py、fusion_v2.py、fusion_session.py及config.py。live.py/fuse.py获准的平台入口发生变化，故另外用原AST回归保护除允许兼容接口以外的算法和调度，不再错误要求两个完整文件逐字不变。

## 新增测试覆盖

模拟Windows/Linux/其他系统的摄像头后端选择；设备路径、尺寸和fps配置；默认后端失败释放后自动选择；显式后端失败；非法配置不打开设备；帧对象及媒体时间接口。音频测试覆盖缺配置、无程序、缺设备参数、非零退出、超时、取消、参数中的空格/引号不经shell执行、Windows WPF/SAPI路径和Linux状态更新。Linux错误路径验证不会调用PowerShell或中止后续处理。

启动脚本使用记录参数的替身程序，没有用伪数据填入产品UI。Git Bash的测试不构成Linux DMS启动、摄像头V4L2或ALSA播放实测。Windows语音实测仅SAPI；Windows MP3分支用进程替身验证命令和成功/失败处理，未重新调用在线服务测试真实MP3解码。

## 调试记录与限制

- 首次受限环境中的异步测试卡在socketpair accept，调用栈定位后在允许本地回环的环境重跑。未修改导航/asyncio业务代码。
- 基线快照初次漏复制模型，导致模型文件缺失；补齐本地四份权重后43项通过，没有下载或伪造模型。
- 音频测试首次清空Windows必需环境变量导致Python子进程初始化失败，修正为只隔离本轮配置键后通过。Git Bash会改写`/dev/video2`，只在测试环境排除该变量转换，未修改Linux生产脚本。
- 本次复用了原测试中“缺少RKNN运行库时退回真实ONNX”的检查；没有安装、转换或调用RKNN/NPU。
- 视频对拍是本地回归素材，不是公开数据准确率评估；不新增误报率、漏报率或ARM64实时性能声明。
- 无真实Linux环境。ARM64 CPU轮子及完整依赖解析、摄像头/音频系统库、触摸屏、实际设备权限、长时性能和资源测试均待完成。

## 后续验收条件

先取得厂商对V2.2及具体屏幕批次、候选镜像和TF写入行为的答复，再按授权范围检查镜像。软件侧先审查ARM64依赖解析，再加载现有模型、对拍同一视频；其后验证V4L2协商参数、音频设备故障处理、原UI和整体CPU/内存/帧率。详见使用说明末尾清单。本轮没有修改Android或访问/写入eMMC。
