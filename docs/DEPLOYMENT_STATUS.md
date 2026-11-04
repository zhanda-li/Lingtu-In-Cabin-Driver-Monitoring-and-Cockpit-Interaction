# 部署与工程状态

资料核对日期：2026-11-04；最新实机记录：2026-11-02。此页统一更新早期“待板端验证”报告的当前状态，原阶段报告保持其历史测试范围。

## 已落地的边缘系统

| 层级 | 实际状态 |
|---|---|
| 平台 | KICKPI K1-MINI V2.2，RK3568B2，4GB/32GB；Ubuntu24.04.4 ARM64、Linux6.1.141 |
| 启动与存储 | 根挂载/dev/mmcblk0p8、启动参数storagemedia=emmc；61,071,360个512B扇区。TF仍插入，未做拔TF冷启动验收 |
| 显示 | Xfce/X11，DSI-1输出对应SoC DSI0，逻辑1280×800；物理800×1280、58.36Hz不改时序 |
| 触摸 | goodix-ts、I2C1/0x5D；单层X11坐标矩阵；用户确认方向与四角/滑动正确 |
| 持久化 | 用户级Xfce登录自动横屏，实际重启验证通过；不代表登录前Logo旋转 |
| 摄像头 | RYS CAMERA102603 USB UVC，V4L2真实读帧；当次/dev/video10和11，路径以后应重新核对 |
| 网络/UI | Wi-Fi有默认路由；HTTP200、WebSocket、原座舱页面和后端模式ACK实测可用 |
| Python | 3.12.3 / glibc2.39 / 独立venv；48个审计运行包及8项补齐依赖安装后pip check通过 |
| 模型 | Pose、Face、原Transformer、Eye/Mouth ONNX五模型独立加载与推理通过 |
| 数值 | Transformer、Eye、Mouth同输入PC/ARM比较通过原容差 |

固件：`update-rk3568-kickpi-k1Mini-linux-ubuntu2404-multi-2026091110.img`。
SHA256：`a69878bc66382d62bf0ad898a00d13e78b68a9fb3aefa79cd27c87e5244abb4b`。

## GPT与系统启动结论

历史RKDevTool/Loader报过备份GPT比对失败。后续运行中Linux独立读取主备GPT各两轮，长度、签名、Header/数组CRC、磁盘GUID和相互引用均通过；备份与原预期file.bin一致，证明并非盘尾0xCC内容。无需重刷或修GPT。原工具失败日志继续保留，责任范围定位于原USB读回/比对链路，闭源工具与Loader的各自责任未分离。Ubuntu实际运行与工具历史失败分别记录，未宣称每个系统分区已完整回读验真。

## 调度改造与性能

单采集源、容量1最新帧、独立预览/推理、快照发布和真实决策去重已在工作区/板端实施。30.16秒窗口送达408张JPEG，约13.53预览FPS；完成45帧推理约1.49FPS，33次不同时间戳决策约1.09FPS。末窗采集29FPS，推理队列1/1，跳过712采集帧，末次结果年龄约1.02–1.18秒。

改造前25秒窗口预览约4.11FPS；该场景未形成有效姿态窗口，前后不是相同工作负载，不用于宣称模型推理加速。后窗Pose/Face/Transformer一次耗时约334.65/107.53/32.74ms。15Hz保留为时序目标，预览FPS与模型FPS分开展示。

最新温度峰值约81.7℃，停止DMS与专用浏览器后约51–53℃。上次已保持空载；本次资料整理不连接板卡、不重新压测。

## 集中待验收项

| 项目 | 已知事实 / 下一步 |
|---|---|
| YOLO实时有效性 | 236条运行诊断里Eye valid均false；慢推理触发原0.5秒异步断档保护。后续测试已有DMS_YOLO_ASYNC=0，不改保护阈值 |
| MediaPipe数值对拍 | Pose最大差0.34502557混合xyz/conf；Face点0.11119843px，混合几何0.08290635；严格容差未通过，需按字段定位 |
| 摄像头重连 | 实际断连、STALE和USB重枚举捕获；首次重开失败。有界就绪重试PC通过、已部署，完整拔插复测待做 |
| 风险/时间可靠性 | 低吞吐下时序重复采样、数据年龄与自然L1/L2验收仍需完成 |
| LR常量 | 原checkpoint元数据YAWN_THR/YAWN_MIN=0.6/2.0与当前0.55/1.0存在既有警告，未改权重或阈值 |
| 语音/外设 | KWS/ASR加载通过；板端实际收音、TTS播放器、扬声器、心率串口和其他硬件未完成闭环 |
| 散热与持续运行 | 长时CPU、内存、温度/FPS验收未通过；先确认散热条件再继续 |
| 模式全流程 | 已有Legacy/V2真实ACK；性能改造后三模式完整启动/退出循环待完成 |
| 网络 | SSH socket监听已查到；实际SSH远程登录另验收 |
| NPU | 本阶段未启用GPU/NPU/RKNN/INT8，不把NPU节点存在当部署成功 |

## 启动与ARM64环境入口

板端既有目录为`/home/kickpi/lingtu_dms_20261102_140748`。桌面“灵途智行DMS”入口与`start_dms.sh legacy|shadow|v2`为该设备部署文件，**不是仓库通用入口**。仓库通用入口为`bash ui/run_ui.sh --mode legacy|shadow|v2`。启动前确认旧服务已退出、设备空闲及散热条件。

复用[ARM64手册](ARM64_SOFTWARE_PREFLIGHT.md)的只读检测、固定输入与逐级测试；当前系统使用[py312约束](../constraints-arm64-py312.txt)和[运行需求草案](../requirements-arm64.txt)。48包草案之外实机补齐httpx、httpcore、anyio、h11、scikit-learn、joblib、threadpoolctl、cloudpickle，共8项；草案本身不是当前完整锁文件，不直接拿早期安装命令宣称完整环境可重建。OpenCV只使用contrib一种发行包，不在板端安装训练导出环境。

验收顺序：系统/显示/触摸→摄像头→依赖→五模型→数值对拍→Legacy→Shadow→V2→Web UI→语音外设→散热/持续运行。每级保存真实输出，不因上一级通过就默认下一级通过。

## 文档发布与源码状态

本次只提交文档、素材和文档检查说明。摄像头调度与横屏工具等性能代码是此前已有的未提交改动，保持原状，不混入文档提交。GitHub资料因此同时说明“已提交模型融合能力”和“实机工作副本调度成果”。个人影像、原始硬件转储、固件、wheel和密钥不公开。

可公开复核的实验来源与本地原始记录SHA索引见[实验来源清单](presentation/EVIDENCE_INDEX.json)。技术资料以[测试报告索引](validation/INDEX.md)为入口；旧阶段未部署声明不覆盖本页的新证据。
