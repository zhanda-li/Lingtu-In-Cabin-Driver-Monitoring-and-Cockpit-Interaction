# 测试报告索引

先按论证目标选报告，再看其日期、平台和范围。旧报告是阶段证据，当前板端状态由[部署状态](../DEPLOYMENT_STATUS.md)统一更新。

| 目标 | 报告/证据 | 使用范围 |
|---|---|---|
| 原输出保护 | [Legacy逐决策回归](legacy_regression.json) | 294决策、19列；本地素材，不是公开准确率 |
| YOLO分类与导出 | [统一PC验收](../yolo_desktop_acceptance.json)、[MRL](../yolo_mrl_labelled_eval.json)、[ONNX](../yolo_onnx_parity.json) | 指定模型、子集与预处理 |
| V2规则/视频解释 | [融合对照](fusion_v2_report.md)、[JSON](fusion_v2_report.json)、[CSV](fusion_v2_yawdd.csv) | 663决策，非带标签误报漏报评估 |
| UI增量保留 | [UI说明](../UI_V2.md)、[结构检查](ui_structure.json)、[WebSocket](fusion_websocket.json) | 原阶段PC界面/协议检查 |
| 摄像头/音频平台适配 | [PC/Linux报告](pc_linux_compat_report.md) | 55项PC；不能替代Linux实机 |
| ARM64依赖与对拍工具 | [67项PC报告](arm64_preflight_report.md)、[py312图](arm64_metadata_py312.json)、[py311图](arm64_metadata_py311.json) | 元数据准备；安装结果另见部署状态 |
| 语音 | [语音报告](voice_interaction_report.md) | 识别/反馈/合成及PC合同，不等于板端扬声器验收 |
| 导航 | [导航报告](navigation_flow_report.md) | 实际三路线规划与13项故障夹具分开 |
| 最新调度/横屏 | [成果与状态](../DEPLOYMENT_STATUS.md)、[本地证据哈希](../presentation/EVIDENCE_INDEX.json) | 76项PC历史通过、真实短时板端测量 |
| 本次资料复核 | [资料升级报告](../PROJECT_DOCUMENTATION_UPDATE_REPORT.md) | 文档/素材/链接/Git与PC测试 |

## 复用现有测试

```powershell
conda activate dms
python -X utf8 -m unittest discover -s tools -p 'test_*.py'
node tools/test_ui_voice.js
node tools/test_nav_flow.js
# 需要原本地normal/fatigue视频、原模型和YOLO权重
python -X utf8 tools/regress_fusion_v2_legacy.py
```

76项完整发现包括尚未提交的`test_camera_pipeline.py`等性能工作副本；仅克隆文档发布分支的测试数可能为原67项。不要为得到相同数量补造测试。本次执行日志见资料报告。没有原数据/模型时视频脚本应报告缺失，不生成代用品。294×19零差异是已有实际回归，本次是否重跑另行标明。

公开数据未来按视频/参与者划分；缺少逐帧可靠真值时报告定性观察或等级分布，误报/漏报/延迟保持未评估。
