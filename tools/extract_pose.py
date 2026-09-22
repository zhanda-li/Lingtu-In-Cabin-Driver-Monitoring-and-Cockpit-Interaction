"""视频 -> MediaPipe Pose 骨骼 CSV。

每个视频输出一个 CSV（= 一个"片段"），每行一帧，列结构：
    frame_idx, timestamp_ms, x0,y0,z0,v0, x1,y1,z1,v1, ... x32,y32,z32,v32

骨骼提取走 src/pose.py，和实时推理是同一份代码、同一个模型文件——
两边不一致会导致"离线测着好、现场一坐就错"。

用法：
    python tools/extract_pose.py                  # 处理 data/raw 下全部视频
    python tools/extract_pose.py --class normal   # 只处理某一类
    python tools/extract_pose.py --overwrite      # 重跑已存在的 CSV
"""

import argparse
import os
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from pose import PoseExtractor

VIDEO_EXT = {".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv"}

COLUMNS = ["frame_idx", "timestamp_ms"] + [
    f"{ax}{i}" for i in range(C.NUM_LANDMARKS) for ax in ("x", "y", "z", "v")
]


def extract_video(path, pose, target_fps=C.TARGET_FPS, ts_base=0.0):
    """跑一个视频，返回 (DataFrame 或 None, 统计信息 dict)。

    pose 由调用方传入并复用：**不要在这里新建 PoseExtractor**。
    mediapipe 的 landmarker 析构要 42 秒且每实例一次，每个视频建一个的话
    40 个片段光析构就 28 分钟。见 src/pose.py 里 close() 的说明。

    ts_base：本段视频的时间戳起点。复用同一个 extractor 时，mediapipe 要求
    时间戳全进程严格递增，而每个视频都从 0 开始计时，所以必须由调用方给
    后续视频加一个递增的偏移。返回的 ts_end 供下一段接着用。
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"打不开视频：{path}")

    src_fps = cap.get(cv2.CAP_PROP_FPS)
    if not src_fps or not np.isfinite(src_fps) or src_fps <= 1:
        print(f"  [warn] 读不到有效帧率，按 30 fps 处理：{path.name}")
        src_fps = 30.0

    step = max(1, int(round(src_fps / target_fps)))
    eff_fps = src_fps / step

    rows = []
    n_read = n_kept = n_no_pose = 0
    t0 = time.perf_counter()

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        idx = n_read
        n_read += 1
        if idx % step:
            continue

        # 传真实时间戳（不是抽帧后的序号），VIDEO 模式据此估计运动速度。
        # 加上 ts_base 是为了让复用的 extractor 看到的全局时间戳始终递增。
        lm = pose.detect(frame, ts_base + idx / src_fps * 1000.0)
        if lm is None:
            n_no_pose += 1
            continue

        rows.append(np.concatenate([[idx, idx / src_fps * 1000.0],
                                    lm.reshape(-1)]))
        n_kept += 1

    cap.release()

    ts_end = ts_base + n_read / src_fps * 1000.0

    if not rows:
        return None, {"read": n_read, "kept": 0, "no_pose": n_no_pose,
                      "fps": 0.0, "seconds": 0.0, "ts_end": ts_end,
                      "elapsed": time.perf_counter() - t0}

    df = pd.DataFrame(np.stack(rows), columns=COLUMNS)
    stats = {
        "read": n_read,
        "kept": n_kept,
        "no_pose": n_no_pose,
        "fps": eff_fps,
        "seconds": n_kept / eff_fps if eff_fps > 0 else 0.0,
        "ts_end": ts_end,
        "elapsed": time.perf_counter() - t0,
    }
    return df, stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--class", dest="cls", choices=C.CLASSES, default=None,
                    help="只处理某一类，默认全部")
    ap.add_argument("--overwrite", action="store_true", help="重跑已存在的 CSV")
    ap.add_argument("--fps", type=float, default=C.TARGET_FPS, help="目标抽帧帧率")
    ap.add_argument("--model", default=None, choices=["lite", "full"],
                    help="覆盖 config.POSE_MODEL_NAME")
    args = ap.parse_args()

    classes = [args.cls] if args.cls else C.CLASSES
    min_frames = int(C.WINDOW / C.TARGET_FPS * 2)

    total = skipped = 0
    t_all = time.perf_counter()

    # 全程只建一个 extractor 反复用。每个视频新建一个的话，析构开销 42 秒/次，
    # 40 个片段要白等 28 分钟。见 src/pose.py 里 close() 的说明。
    pose = PoseExtractor(args.model)
    ts_base = 0.0        # 全局时间戳偏移，保证复用的 extractor 看到的时间戳递增

    for cls in classes:
        src_dir = C.DATA_RAW / cls
        dst_dir = C.DATA_POSE / cls
        dst_dir.mkdir(parents=True, exist_ok=True)

        videos = sorted(p for p in src_dir.glob("*") if p.suffix.lower() in VIDEO_EXT)
        if not videos:
            print(f"[{cls}] {src_dir} 下没有视频，跳过")
            continue

        print(f"[{cls}] 发现 {len(videos)} 个视频")
        for v in videos:
            out = dst_dir / f"{v.stem}.csv"
            if out.exists() and not args.overwrite:
                print(f"  - {v.name}  已存在，跳过（--overwrite 可重跑）")
                skipped += 1
                continue

            # 清掉上一段遗留的"低置信点沿用上一帧"状态。
            # 注意：mediapipe 内部的跟踪器无法重置，所以每段开头一两帧可能
            # 还带着上一段的姿态。影响很小（150 帧里的 1~2 帧），可忽略。
            pose.reset()

            df, st = extract_video(v, pose, args.fps, ts_base)
            ts_base = st["ts_end"] + 1000.0     # 段间留 1 秒空档
            if df is None:
                print(f"  - {v.name}  [失败] 全程没检测到人体，该片丢弃"
                      f"（读入 {st['read']} 帧）")
                continue

            df.to_csv(out, index=False)
            rate = st["no_pose"] / max(st["read"], 1) * 100
            print(f"  - {v.name}  -> {out.name}")
            print(f"      读入 {st['read']} 帧 / 保留 {st['kept']} 帧 "
                  f"/ 未检出 {st['no_pose']} 帧 ({rate:.1f}%) "
                  f"/ {st['seconds']:.1f} s / {st['fps']:.1f} fps "
                  f"/ 提取耗时 {st['elapsed']:.1f} s")
            if rate > 20:
                print("      [warn] 未检出率偏高，检查光线或摄像头取景")
            if st["kept"] < min_frames:
                print(f"      [warn] 有效帧不足 {min_frames}，样本太少，建议重录长一点")
            total += 1

    print(f"\n完成：新提取 {total} 个片段，跳过 {skipped} 个，"
          f"总耗时 {time.perf_counter() - t_all:.1f} s。")

    # 必须是 main() 的最后一行：mediapipe 的 landmarker 析构固定耗时 42 秒，
    # 而 pose 是 main() 的局部变量，main() 一返回它就开始析构。
    # os._exit 永不返回 => 函数不返回 => 不析构。放到 if __name__ 里就晚了。
    # 所有 CSV 上面都已落盘，跳过解释器清理是安全的。见 src/pose.py。
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
