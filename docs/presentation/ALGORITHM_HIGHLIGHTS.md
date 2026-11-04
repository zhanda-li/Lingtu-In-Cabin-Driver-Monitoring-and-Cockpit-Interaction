# 算法亮点：多尺度、时序与证据协同

## 亮点一：身体动作的时间建模

单帧姿态难以描述点头的下探与回弹。Pose33点×4维进入原归一化和45帧窗口，Transformer通过CLS与自注意力提取时序表征。当前输入45×132、时间目标15Hz、实际二分类normal/fatigue，原checkpoint保留。

**PPT建议：**画三帧身体动作及一个45帧窗口，输出接Transformer Evidence；不将nod统计频率画成已实现的独立点头周期检测。

## 亮点二：几何与外观共同描述眼嘴

同一FaceLandmarker既提供EAR/MAR/PERCLOS/头姿，也为左右眼与嘴部YOLO分类定位ROI。Eye输出两眼各自概率，Mouth输出Yawn/No Yawn。几何刻画相对形变，分类模型提供局部纹理和外观支持，形成可记录的一致或冲突状态。

**PPT建议：**用输入示意框表达三个ROI，但不要将示意框称为YOLO目标检测结果。两份权重是224×224分类模型；MRL子集356/371支持的是眼图分类能力。

## 亮点三：按证据组处理相关性

Eye融合EAR/PERCLOS和双眼分类，Mouth融合MAR/分类/持续时间，Head结合头姿与Transformer趋势。FaceBranch与Eye共享特征，取最大组成眼部家族。五组序数证据合成风险，而不是把相关模型概率简单求和。

**PPT建议：**五组证据并排，Eye与FaceBranch画共享信息连线；突出“组内共识、组间融合、时间约束”。

## 亮点四：风险与可靠性一起输出

valid、warmup、stale、conflict与等级原因同步发布；缺失不伪装正常；两路YOLO不可用退回Legacy。进入保持与降级滞回处理等级变化。模式由后端确认，V2输出可与Legacy逐决策对照。

**讲解重点：**解释“为什么是这一等级”与“哪些证据可用”，体现可观察、可回退的融合工程。当前融合为可配置规则，不称最优权重、新训练融合器或已校准总体概率。

[完整输入与阈值来源](../ALGORITHM_ARCHITECTURE.md) · [真实对照数据](DEMO_AND_EXPERIMENTS.md)
