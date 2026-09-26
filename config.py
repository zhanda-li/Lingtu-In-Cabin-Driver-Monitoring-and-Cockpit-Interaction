"""全局配置：路径、类别定义、窗口参数、归一化参数。

所有脚本共用这一份。改参数只改这里，不要在各个脚本里散落魔数。
"""

import sys
from pathlib import Path

# Windows 控制台默认编码是 GBK：中文日志会显示成乱码，一旦重定向到文件
# 或被子进程捕获，还会直接抛 UnicodeEncodeError。所有脚本都 import 本模块，
# 在这里统一把标准输出强制成 UTF-8，一劳永逸。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ---------------- 路径 ----------------
ROOT = Path(__file__).resolve().parent
DATA_RAW = ROOT / "data" / "raw"          # 原始视频：data/raw/<类别>/xxx.mp4
DATA_POSE = ROOT / "data" / "pose"        # MediaPipe 输出：data/pose/<类别>/xxx.csv
DATA_DATASET = ROOT / "data" / "dataset"  # 切分好的 npz
RUNS = ROOT / "runs"                      # 训练输出、图表

# ---------------- 类别 ----------------
# 顺序即标签 id。改了它已训练的权重要重训，模型权重和这个顺序绑定。
#
# ★ 2026-09-24：四类 -> 三类，**`glance`（短暂扭头=分心）删除**。
# 用户原话：「后端改一下 我们只做疲劳」「phone 直接归为重度疲劳 fatigue依旧是
# 疲劳 glance删掉」「轻度疲劳就是支路2的闭眼时间变长 打哈欠那些」「重度疲劳就是
# 点头 低头 头部倾倒这些」。
# 于是：**看手机 = 持续低头 = 重度疲劳**，点和点是同一件事的两种姿态。
#
# ★ 2026-09-25：三类 -> 二类，**`phone` 并入 `fatigue`**。
# 用户原话：「点头这个 直接 疲劳瞌睡点头和头部持续低头变成一路吧」
#        「glance不参与训练了 phone和fatigue数据集相当于一种」。
# 三条理由（详见 plans/transient-sleeping-llama.md）：
#   · 界面上"疲劳瞌睡点头"和"头部持续低垂"两根条并排，模型老把两者搞混
#     （三类下测试集 45 个错里 24 个是这一对），而产品口径里它们**本来就同属
#     重度疲劳**（`src/live.py` 的 CLASS_LEVEL 把两者都落 L3）—— 分开只是
#     徒增一处误报来源。
#   · 合并后 `ema[normal] + ema[fatigue] = 1`，于是
#     `ema[fatigue] > ENTER_TH` **等价于** `ema[normal] < EXIT_TH`，
#     也就是"闸门关闭 ⟺ 判重度"这两件事从代数上合成了一件。
#   · 但这条恒等式**放宽了**重度的触发（原先要"某一类过 0.60"，现在是
#     "非正常这一类过 0.60"，而 `ema[normal]` 掉到 0.40 就够）—— 所以
#     `glance` 那 27 段退掉的样本要当**负对照**量一遍，见验收 1.6。
#
# 数据侧**非破坏**：`data/pose/{glance,phone}/` 与 `data/raw/{glance,phone}/`
# 全部原地保留，只是 `tools/build_dataset.py` 按目录打新标签
# （`DIR_CLASS`：phone 目录 -> fatigue 类）。想回到三类就把 CLASSES 改回去、
# 并把 `DIR_CLASS` 里的 phone 还原，再重训（旧权重在 runs/fatigue3/ 下留着）。
CLASSES = ["normal", "fatigue"]
CLASS_NAMES_CN = ["正常驾驶", "疲劳"]
NUM_CLASSES = len(CLASSES)

# ---------------- 骨骼 ----------------
NUM_LANDMARKS = 33            # MediaPipe Pose 关键点数
FEAT_PER_LANDMARK = 4         # x, y, z, visibility
FEAT_DIM = NUM_LANDMARKS * FEAT_PER_LANDMARK   # 132

L_SHOULDER, R_SHOULDER = 11, 12   # 归一化用的原点/尺度基准点

# visibility 低于此值视为不可信，坐标沿用该点上一帧的有效值
VIS_THRESHOLD = 0.5

# 肩宽序列的滑动中位数窗长（帧）。单帧肩宽抖动会污染全部坐标，压掉它。
SCALE_SMOOTH_WIN = 15

# ---------------- 时序 ----------------
TARGET_FPS = 15        # 统一抽帧到 15 FPS
# 窗口长度（帧）= 3 秒。**这个值是实测选的，不是推理的。**
# 原先写 60（4 秒）的理由是"必须覆盖一个完整点头周期（1~4 s）"，从没验证过；
# `tools/sweep_window.py` 按不同窗口各训一个模型实测，结果推翻了这个说法：
# fatigue/phone/glance 三类在 15 帧（1 秒）下就已经是 100%、混淆对概率 0.02~0.07。
# 而窗口长度直接决定响应延迟，`tools/sweep_step.py` 实测阶跃响应：
#   60 帧 -> 平均 3.8 s 才升到 L1     45 帧 -> 平均 1.0 s
# 45 帧下 24 个片段级别全对、零误报，所以取 45。
# 再往下压到 30 帧能到 1.6 s，但 normal 那一类准确率掉到 0（只有 6 段正常样本、
# 其中 normal_03 本身偏），**先补 normal 数据再压**。
WINDOW = 45
STRIDE_TRAIN = 15      # 训练滑窗步长（重叠 67%，同时起数据增广作用）
STRIDE_INFER = 1       # 推理时每帧都评，保证响应速度

# ---------------- 数据集划分 ----------------
# 关键：按【录制片段】整体划分，绝不按窗口随机划分。
# 否则相邻窗口重叠，会同时落进训练集和测试集，测试准确率虚高。
SPLIT_SEED = 42
SPLIT_RATIO = (0.75, 0.125, 0.125)   # train / val / test
MIN_CLIPS_PER_CLASS = 6              # 每类至少这么多段，否则划分太薄要告警

# ---------------- MediaPipe ----------------
# 提取（离线）和实时推理必须共用同一个模型文件、同一套参数，
# 否则训练时的输入分布和推理时的对不上，准确率会莫名暴跌。
#
# 注意：mediapipe 1.0 移除了老的 mp.solutions.pose，改用 Tasks API，
# 模型是独立的 .task 文件。已随项目附带在 models/ 下，现场不联网。
MODELS_DIR = ROOT / "models"
POSE_MODEL_NAME = "full"     # full 精度好；现场若卡顿改成 "lite"
POSE_NUM_POSES = 1
POSE_MIN_DETECTION_CONF = 0.5
POSE_MIN_PRESENCE_CONF = 0.5
POSE_MIN_TRACKING_CONF = 0.5

# ---------------- 训练 ----------------
SEED = 42
BATCH_SIZE = 64
EPOCHS = 60
LR = 3e-4
WEIGHT_DECAY = 1e-4
D_MODEL = 64
N_HEAD = 4
N_LAYER = 3
DROPOUT = 0.1
LABEL_SMOOTH = 0.05
