# 项目技术资料升级报告

日期：2026-11-04（Asia/Shanghai）。项目分支：feat/yolo-face-shadow；实现基线2f0a379。

## 交付成果

重新组织README，以项目价值、多模型协同、系统闭环和实验支撑为主线。新增系统架构、算法架构、当前部署状态、测试报告索引；PPT交接目录提供六份核心资料、两张真实PC截图、来源与哈希索引。原README全文保存为根目录README_LEGACY.md，包含用户已有DMA心率描述，另在项目外保存修改前副本。

| 文件 | 内容 |
|---|---|
| [README](../README.md) | 新展示入口、模型关系、成果、启动方法与资料导航 |
| [系统架构](SYSTEM_ARCHITECTURE.md) | 模块、数据流、WebSocket与调度关系 |
| [算法架构](ALGORITHM_ARCHITECTURE.md) | 模型输入输出、完整Legacy、五组V2、时间与有效性 |
| [部署状态](DEPLOYMENT_STATUS.md) | Ubuntu/eMMC、显示触摸、五模型、性能与集中待验收项 |
| [测试索引](validation/INDEX.md) | PC规则/视频/跨平台/语音/导航及板端证据边界 |
| [PPT交接](presentation/PPT_HANDOFF.md) | 11个关键问题与12页推荐叙事 |
| [项目概览](presentation/PROJECT_OVERVIEW.md) | 背景、目标、路线、应用价值 |
| [算法亮点](presentation/ALGORITHM_HIGHLIGHTS.md) | 时序、局部外观、相关证据管理与可靠性 |
| [PPT架构](presentation/SYSTEM_ARCHITECTURE.md) | 可渲染Mermaid及图注 |
| [演示与实验](presentation/DEMO_AND_EXPERIMENTS.md) | 真实数据、论证职责及统计范围 |
| [素材索引](presentation/PPT_ASSET_INDEX.md) | 图片来源、用途、授权范围与待补清单 |
| [来源清单](presentation/EVIDENCE_INDEX.json) | 复核文件哈希，标记公开与本地原始记录 |

已有FUSION_V2、UI_V2、ARM64_SOFTWARE_PREFLIGHT、PC_LINUX_COMPATIBILITY四份指南增补当前状态入口；不改写旧阶段验证报告，不将其历史“尚未部署”套用到当前硬件。

## 事实修正与写作方式

- 准确表示当前Transformer为normal/fatigue二分类，45×132、15Hz时间目标；旧三分类模型数量/准确率留作历史，不冒充当前模型。
- 两份YOLO权重为224分类模型，左右眼独立，嘴部与MAR持续性互证；V2是真实参与，Shadow仍最终Legacy。
- Legacy包含原几何闭眼/哈欠/头动规则，不再用旧简化公式或“L3必来自姿态”概括全部逻辑。
- Ubuntu/eMMC启动、五模型独立运行、X11横屏持久化和Goodix用户确认写为成果；GPT旧失败与Linux后续有效主备GPT证据分开。
- 13.53为短时预览FPS，1.49为实际推理FPS；不把预览、重复消息或设备协商30fps当15Hz算法吞吐。
- MRL95.96%明确子集；V2不同等级不当误报率；推理时延/资源范围有标注。未标定项目集中写入工程状态。
- 遵循[用户指定写作原则](https://github.com/Adkid-Zephyr/anti-defensive-writing-Skill/blob/main/skills/anti-defensive-writing/SKILL.md)：围绕贡献组织，以证据支持主张；事实准确与完整保留用户修改优先。

## 本次验证

现有PC单元测试本次完整复跑：**76项通过，18.742秒**。包含原67项与工作副本9项调度测试；受限环境首次运行未完成，停止后在正常权限下重跑，只以完整成功日志为通过依据。本次没有打开摄像头、连接板卡或重启实机负载。

现有node检查：test_ui_voice.js六组通过，test_nav_flow.js通过。本次为合同/逻辑检查，不是重新做浏览器视觉验收或扬声器听感验收。原视频对拍本次已完成：正常167次、疲劳127次，共294次决策，19列再次全部零差异。日志见[本次PC执行记录](validation/documentation_tests.txt)；未重录或训练。

PC和板端结果分别标注；现有67/76项、294×19、512组合、MRL、ONNX、YawDD与板端短时数据都有具体来源。板端原始日志及真人截图保持本地，仅发布文字摘要和原始文件哈希，不发布固件、wheel或模型。

## 文档与素材检查

当前入口及四份更新指南的本地链接按文件存在、提交范围及Markdown锚点检查；结果见[链接检查JSON](validation/documentation_links.json)。历史README全文保留，不纳入当前入口链接验收。7个当前范围外部URL通过HTTP HEAD返回200，见[外链记录](validation/documentation_external_links.json)；不声称历史存档内全部网址已重查。两张素材逐字节与既有公开图一致，没有新增真人截图。

## Git保护与发布

用户指定发布仓库为Lingtu-In-Cabin-Driver-Monitoring-and-Cockpit-Interaction，已再次明确确认；原origin仍指Cockpit-Driver-State-Monitor，保持不改。目标远端feat/yolo-face-shadow为c0619f3，是本地HEAD祖先；不存在需要强推的分叉。main不修改。

本次文档提交只选择显式文件清单，不使用git add .。原hr三个文件、tools/record.py及性能优化ui代码保持未提交状态；不覆盖已有改动。文档对应当前真实工作区与实机成果，明确其调度源码尚待单独提交。

本地2f0a379相对目标远端已有10个未同步功能提交；本次正常快进推送也会同步这些既有提交（V2、语音、导航、PC/Linux及ARM64准备），不将当前未提交源码带入。提交与远端实测记录在操作完成后追加。

## 后续工程验收

先处理散热与连接条件，再验证摄像头完整重连、原YOLO同步选项、MediaPipe字段级数值差异、三模式完整启动/释放、长时CPU/内存/温度、板端收音/播报及其他硬件。无重训、无规则阈值更改、无UI重做、无固件操作。详见[当前工程状态](DEPLOYMENT_STATUS.md)。
