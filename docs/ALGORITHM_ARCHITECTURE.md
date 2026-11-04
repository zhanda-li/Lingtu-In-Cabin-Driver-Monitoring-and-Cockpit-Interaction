# 算法架构：多尺度感知与分组证据融合

系统以身体动作的时间变化、面部几何和眼嘴局部外观互补描述驾驶员状态。Fusion V2 将这些观测组织为证据组，使最终风险能够追溯到具体模型、持续时间与一致性条件。

## 输入、模型与输出

| 模块 | 输入与实现 | 输出 / 进入融合的方式 |
|---|---|---|
| Pose | 原 BGR 图像转 RGB，PoseLandmarker Tasks VIDEO，33点 | xyz+visibility/presence；低置信历史有效点沿用原策略 |
| 姿态时序 | 原归一化与时间采样；45帧×132维 | Transformer normal/fatigue posterior、原姿态等级 |
| Transformer | 线性投影，CLS与位置编码，3层Encoder，d_model64，4 heads | 当前二分类；不把旧三分类实验数字当作当前checkpoint结果 |
| Face | 同一 FaceLandmarker，478点 | EAR、MAR、Pitch/Yaw/Roll、头动及ROI位置 |
| 面部统计 | 原窗口与归一化定义 | PERCLOS、brate、nod、哈欠持续量；nod是原统计频率 |
| LR | FEATURE_NAMES固定为 `(perclos, brate, nod)` | `predict_proba`、原l2；MAR/yawn不新增为LR输入 |
| Eye YOLO | 左眼、右眼各一张224×224 ROI | 类别0=closed、1=open；左右分别推理 |
| Mouth YOLO | 一张224×224嘴部ROI | 类别0=no_yawn、1=yawn；与MAR/持续时间形成候选 |

FaceExtractor 完成原几何计算后将同一关键点字典交给 ROI 模块，不运行第二套 FaceMesh。眼嘴模型是 YOLOv8 分类权重；输出是局部状态概率，不是目标框或校准的驾驶疲劳概率。

原在线归一化以双肩中点为原点、双肩距离的历史滑动中位数为尺度，归一化xyz并保留置信度，展平成132维。离线历史实现采用居中尺度中位窗，在线采用因果历史窗；本轮不改变这项既有差异。

## ROI 与时间证据

ROI 有边界裁切、缺点、空图和越界检查。人脸丢失、无效 ROI、时间倒退/断档或结果过期均使对应概率无效，不能解释为闭眼或哈欠。原 Shadow 采用时间平滑；0.05–0.8秒闭眼释放可记录眨眼，0.8秒持续闭眼记录长闭眼；嘴部需概率>0.8、MAR>0.55并连续1.5秒形成候选。Shadow 事件阈值与 V2 风险组持续阈值分别定义。

YOLO 的 `sample_timestamp` 标识输入样本；异步队列有界，过期保护为0.5秒。原模型加载/导出信息见[权重与验证](YOLO_SHADOW.md)。

## Legacy：完整保留的参考策略

不能用旧 README 的 `max(l1,min(l2,2))` 代替全部现行规则。当前 `src/fuse.py` 与摄像头链路先计算：

```text
l_face = min(l2, B2_MAX_LEVEL) if gate else 0
l_base = max(l1, l_face)
l_yawn = 1 if yawn_on and YAWN_ACTION == "level" else 0
l_eye = EYE_LEVEL if eye_on else 0
l_head = HEAD_LEVEL if head_on else 0
l_fused = max(l_base, l_yawn, l_eye, l_head)
```

原闸门、状态机、锁存、来源优先级及参数保留，因此不能再写“所有L3必须来自Transformer”。LR支路受上限约束，独立规则仍可产生自己的风险等级。`src/fuse.py` 为原版回归参考。

## Fusion V2：五组证据

| 证据组 | 核心规则 | 相关性与可靠性处理 |
|---|---|---|
| Eye | 归一化EAR<0.8，左右YOLO分类，PERCLOS趋势，闭眼持续 | 双眼各自有效；EAR/YOLO矛盾或左右不对称标记冲突，不叠加分值 |
| Mouth | MAR>0.55，Yawn>0.8，持续至少1.5秒 | 单组最高L1；单帧张嘴无升级，冲突时保留解释 |
| Head/Posture | 原head_swing≥10°，持续下探，Transformer持续支持 | 短暂低头不在V2直接形成L3；nod定义不变 |
| Transformer | 原fatigue posterior≥0.6的持续趋势 | 单独最高L2；与头部持续共识可形成L3 |
| FaceBranch | 原LR概率、l2、fb.full、gate、有效样本数 | 热身/无效样本不投票；与Eye取最大形成眼部家族 |

V2 对独立证据取序数最大值；眼部家族与持续嘴部证据可共同支持L2。几何与双眼分类一致且连续严重闭眼，或持续头部/Transformer共识，可支持L3。原45/15=3秒用于严重持续阈值；进入保持0.5秒、降级保持1.5秒。PERCLOS轻/中阈值0.187/0.426沿用原UI参数来源。

这些组合是可配置、可解释的工程策略，来源见[完整规则表](FUSION_V2.md)。没有训练新的融合模型，也没有将权重宣称为最优。独立 nod_event 尚未实现，现有 nod 不等于完整点头周期计数。

## 模式选择、退化与输出

每次先得到真实 Legacy 结果，再计算 V2 对照。只有显式选择 V2 才将 `State.l_fused` 设为 V2 最终等级；Legacy/Shadow 保持原结果。V2 同时要求允许开关、通过的基本验收报告、策略与源码SHA匹配。选择结果统一驱动风险展示与告警原因。

每组输出 valid/confidence/timestamp/stale/warmup。两路 YOLO 均不可用时精确回退 Legacy，并记录原因；这不是确认驾驶员正常。总体 `confidence=null`，语义为 `ordinal_rules_not_probability`。自然说话、大笑、唱歌的区分能力需要带标签视频验收，不能由规则单测代替。

## 验证与复现

512组合保护原规则；294次/19列逐决策对拍保护Legacy；YawDD的663条真实模型特征记录验证两版解释链路。模型导出比较固定同张量，跨架构比较固定原图、姿态窗和ROI，分别隔离模型推理和预处理。

[实验口径](presentation/DEMO_AND_EXPERIMENTS.md) · [测试索引](validation/INDEX.md) · [当前板端限制](DEPLOYMENT_STATUS.md)
