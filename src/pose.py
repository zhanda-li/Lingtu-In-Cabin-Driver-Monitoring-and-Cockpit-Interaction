"""MediaPipe 骨骼提取的统一封装。

**离线提取和实时推理必须共用这一份。** 两边各写一套的话，模型文件、置信度
阈值、低置信点的处理方式稍有不同，训练和推理的输入分布就对不上，
表现是"离线测试 95%，现场一坐上去全错"。

mediapipe 1.0 移除了老的 mp.solutions.pose，这里用新的 Tasks API。
模型文件在 models/ 下随项目附带，现场不联网。
"""

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C


def model_path(name=None):
    return C.MODELS_DIR / f"pose_landmarker_{name or C.POSE_MODEL_NAME}.task"


class PoseExtractor:
    """一帧 BGR -> (33, 4) 骨骼数组，没检测到人返回 None。

    第 4 列是置信度（visibility，缺失时退回 presence）。
    置信度低于 C.VIS_THRESHOLD 的点，坐标沿用该点上一帧的有效值——
    比直接置零好，置零会让不可信的点全挤在原点，凭空造出错误的几何。
    """

    def __init__(self, name=None, running_mode="VIDEO"):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        path = model_path(name)
        if not path.exists():
            raise FileNotFoundError(
                f"找不到模型文件 {path}\n"
                f"从 https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
                f"pose_landmarker_{name or C.POSE_MODEL_NAME}/float16/latest/"
                f"pose_landmarker_{name or C.POSE_MODEL_NAME}.task 下载后放进 models/")

        opts = vision.PoseLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path)),
            running_mode=(vision.RunningMode.VIDEO if running_mode == "VIDEO"
                          else vision.RunningMode.IMAGE),
            num_poses=C.POSE_NUM_POSES,
            min_pose_detection_confidence=C.POSE_MIN_DETECTION_CONF,
            min_pose_presence_confidence=C.POSE_MIN_PRESENCE_CONF,
            min_tracking_confidence=C.POSE_MIN_TRACKING_CONF,
            output_segmentation_masks=False,
        )
        self._landmarker = vision.PoseLandmarker.create_from_options(opts)
        self.running_mode = running_mode
        # 全进程单调递增，**跨视频也不能重置**：mediapipe 的图会拒绝倒退的
        # 时间戳（ValueError: Input timestamp must be monotonically increasing）。
        self._last_ts = -1
        self.reset()

    def reset(self):
        """清掉上一段视频遗留的时序状态（换视频时调用）。

        只清"低置信点沿用上一帧"的状态，**不动 _last_ts**——它是全进程
        时间戳单调性的守卫。新视频的时间戳从 0 重新开始，所以调用方还得
        自己给新视频加一个递增的时间偏移，见 tools/extract_pose.py 的 ts_base。
        """
        self._seen = np.zeros(C.NUM_LANDMARKS, dtype=bool)
        self._last = np.zeros((C.NUM_LANDMARKS, C.FEAT_PER_LANDMARK), np.float32)

    def detect(self, bgr, timestamp_ms):
        """一帧 BGR 图 + 该帧时间戳(ms) -> (33,4) 或 None。

        VIDEO 模式要求时间戳严格递增，这里做了兜底。
        """
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                             data=np.ascontiguousarray(rgb))

        ts = int(timestamp_ms)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts

        if self.running_mode == "VIDEO":
            res = self._landmarker.detect_for_video(img, ts)
        else:
            res = self._landmarker.detect(img)

        if not res.pose_landmarks:
            return None

        pts = res.pose_landmarks[0]
        xyz = np.array([[p.x, p.y, p.z] for p in pts], dtype=np.float32)
        vis = np.array([p.visibility for p in pts], dtype=np.float32)
        pres = np.array([p.presence for p in pts], dtype=np.float32)
        # 有的版本只填 presence、visibility 全 0，这里兜一下
        conf = vis if np.any(vis > 0) else pres
        lm = np.concatenate([xyz, conf[:, None]], axis=1).astype(np.float32)

        low = lm[:, 3] < C.VIS_THRESHOLD
        fill = low & self._seen                      # 只有该点历史上有效过才填
        lm[fill] = self._last[fill]
        self._seen |= ~low
        self._last[~low] = lm[~low]
        return lm

    def close(self):
        """显式释放底层 landmarker。**正常不要调用。**

        实测（mediapipe 1.0.1 / Windows / 本机）：close() 固定耗时 **42 秒**，
        和模型大小无关，而且**每个实例都要付一次** —— 40 个片段就是 28 分钟
        纯浪费。真正的检测只占 2.3 秒。

        ⚠️ 调不调它只决定这 42 秒**什么时候**付，不决定它是否发生：
        不调则推迟到持有它的那个函数的局部变量被销毁时（通常是 main() 返回）。
        曾经这里写着"不调就是瞬时的"——**错的**，那是因为当时把它放成了模块级
        全局变量，而模块全局在解释器关闭时不会被析构。

        正解是把 `os._exit(0)` 放在 `main()` 的**最后一行**（os._exit 永不返回
        => 函数不返回 => 局部变量不析构）。写进 `if __name__ == "__main__":`
        里无效，那时 main() 已经返回、析构已经跑完了。
        `tools/extract_pose.py` / `tools/record.py` / `src/live.py` 都照此办理。
        """
        try:
            self._landmarker.close()
        except Exception:
            pass
        self._landmarker = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        # 故意不调 close()：调了要卡 42 秒，见 close() 的说明
        return False
