"""长闭眼 = 持续时间问题。正常眨眼峰值也能到 0.5+，区别在能撑几帧。
15 fps 下：正常眨眼 0.1~0.4s = 1.5~6 帧；瞌睡长闭眼 >1s = >15 帧。
"""
import os, sys
from pathlib import Path
import cv2, numpy as np
ROOT=Path(__file__).resolve().parent.parent; sys.path.insert(0,str(ROOT))
import config as C
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision

lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
    base_options=mp_python.BaseOptions(model_asset_path=str(C.MODELS_DIR/"face_landmarker.task")),
    running_mode=vision.RunningMode.VIDEO, num_faces=1, output_face_blendshapes=True))

def runs(v, th):
    """最长连续超阈帧数 + 超阈段数(>=8帧即0.53s)"""
    best=cur=cnt=0
    for x in v:
        if x>th: cur+=1
        else:
            if cur>=8: cnt+=1
            best=max(best,cur); cur=0
    if cur>=8: cnt+=1
    return max(best,cur), cnt

def scan(cls, names, ts0=0):
    ts=ts0; out=[]
    for name in names:
        cap=cv2.VideoCapture(str(C.DATA_RAW/cls/f"{name}.mp4"))
        fps=cap.get(cv2.CAP_PROP_FPS) or 30.0
        step=max(1,int(round(fps/C.TARGET_FPS)))
        bl,jw,k,i=[],[],0,0
        while True:
            ok,fr=cap.read()
            if not ok: break
            idx=i; i+=1
            if idx%step: continue
            k+=1
            r=lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                data=np.ascontiguousarray(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB))),
                ts+int(k/C.TARGET_FPS*1000))
            if not r.face_blendshapes: continue
            d={c.category_name:c.score for c in r.face_blendshapes[0]}
            bl.append((d["eyeBlinkLeft"]+d["eyeBlinkRight"])/2); jw.append(d["jawOpen"])
        cap.release(); ts+=int(k/C.TARGET_FPS*1000)+1000
        if not bl: out.append((name,None)); continue
        bl=np.array(bl); jw=np.array(jw)
        out.append((name, dict(
            bl_med=float(np.median(bl)), bl_max=float(bl.max()),
            run4=runs(bl,0.4), run5=runs(bl,0.5), run6=runs(bl,0.6),
            jw_max=float(jw.max()), jw_run=float((jw>0.5).sum()))))
    return out

FAT=[f"fatigue_{i:02d}" for i in range(26)]
NOR=[f"normal_{i:02d}" for i in range(26)]
for cls,names in [("normal",NOR)]:
    res=scan(cls,names); ok=[r for r in res if r[1]]
    print(f"\n===== {cls}  (有效 {len(ok)}/{len(res)}) =====")
    print(f"{'片段':<12}{'中位':>7}{'最大':>7}{'>0.4最长':>10}{'>0.5最长':>10}{'>0.6最长':>10}"
          f"{'(秒)':>8}{'段数>=8帧':>10}{'jaw最大':>9}")
    for name,d in res:
        if not d: print(f"{name:<12}   没检出人脸"); continue
        L4,c4=d['run4']; L5,c5=d['run5']; L6,_=d['run6']
        flag="  <== 疑似长闭眼" if L5>=12 else ""
        print(f"{name:<12}{d['bl_med']:>7.3f}{d['bl_max']:>7.3f}{L4:>10}{L5:>10}{L6:>10}"
              f"{L5/15:>8.2f}{c4:>10}{d['jw_max']:>9.3f}{flag}")
    lat=[d['run5'][0] for _,d in res if d]
    mx=[d['run5'][0] for _,d in res if d]
    print(f"  -> >0.5 最长段：中位 {np.median(mx):.0f} 帧 ({np.median(mx)/15:.2f} s)，"
          f"最大 {max(mx):.0f} 帧 ({max(mx)/15:.2f} s)，"
          f">=15帧(1s)的片段数 {sum(1 for m in mx if m>=15)}/{len(mx)}")
    jw=[d['jw_max'] for _,d in res if d]
    print(f"  -> jawOpen 最大：中位 {np.median(jw):.2f}，最大 {max(jw):.2f}")
sys.stdout.flush(); sys.stderr.flush(); os._exit(0)
