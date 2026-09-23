"""测两件事：eyeBlink 在真闭眼时能不能冲到高位（长闭眼），jawOpen 有没有哈欠峰。
关键看**峰值**不是中位数——长闭眼和哈欠都是大事件，中位数会把它们平均掉。
"""
import csv, os, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C

PICKS = [("fatigue","fatigue_16"),("fatigue","fatigue_13"),("fatigue","fatigue_01"),
         ("fatigue","fatigue_09"),("normal","normal_14"),("normal","normal_19")]
# 嘴部裁剪用的界标：13上唇 14下唇 61左嘴角 291右嘴角
EYE_PTS  = [33,133,362,263,468,473]
MOUTH_PTS = [13,14,61,291]

def box(frame, lms, pts, aspect, pad=0.85, upscale=(360,140)):
    h,w = frame.shape[:2]
    px = [(int(lms[i].x*w), int(lms[i].y*h)) for i in pts]
    xs=[p[0] for p in px]; ys=[p[1] for p in px]
    cx=(min(xs)+max(xs))//2; cy=(min(ys)+max(ys))//2
    hw=max(50,int((max(xs)-min(xs))*pad)); hh=max(20,int(hw*aspect))
    x0,x1=max(0,cx-hw),min(w,cx+hw); y0,y1=max(0,cy-hh),min(h,cy+hh)
    if x1-x0<20 or y1-y0<10: return None
    return cv2.resize(frame[y0:y1,x0:x1], upscale, interpolation=cv2.INTER_CUBIC)

def main():
    import mediapipe as mp
    from mediapipe.tasks import python as mp_python
    from mediapipe.tasks.python import vision
    lm = vision.FaceLandmarker.create_from_options(vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(model_asset_path=str(C.MODELS_DIR/"face_landmarker.task")),
        running_mode=vision.RunningMode.VIDEO, num_faces=1, output_face_blendshapes=True,
        min_face_detection_confidence=0.5, min_face_presence_confidence=0.5,
        min_tracking_confidence=0.5))
    ts_base = 0
    print(f"{'片段':<12}{'检出':>5}{'blink中位':>10}{'blink P95':>11}{'blink 最大':>11}"
          f"{'>0.6占比':>10}{'jaw中位':>9}{'jaw P95':>9}{'jaw 最大':>9}")
    print("-"*100)
    sheets = {}
    for cls, name in PICKS:
        cap = cv2.VideoCapture(str(C.DATA_RAW/cls/f"{name}.mp4"))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        step = max(1,int(round(fps/C.TARGET_FPS)))
        bl, jw, eye_c, mouth_c, k, i = [], [], [], [], 0, 0
        while True:
            ok, fr = cap.read()
            if not ok: break
            idx=i; i+=1
            if idx%step: continue
            k+=1
            res = lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
                     data=np.ascontiguousarray(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB))),
                     ts_base+int(k/C.TARGET_FPS*1000))
            if not res.face_blendshapes: continue
            d = {c.category_name: c.score for c in res.face_blendshapes[0]}
            b = (d["eyeBlinkLeft"]+d["eyeBlinkRight"])/2
            bl.append(b); jw.append(d["jawOpen"])
            eye_c.append(box(fr, res.face_landmarks[0], EYE_PTS, 0.38))
            mouth_c.append(box(fr, res.face_landmarks[0], MOUTH_PTS, 0.55))
        cap.release(); ts_base += int(k/C.TARGET_FPS*1000)+1000
        if not bl: print(f"{name:<12}{'0%':>5}  没检出人脸"); continue
        bl=np.array(bl); jw=np.array(jw)
        print(f"{name:<12}{len(bl):>5}{np.median(bl):>10.3f}{np.percentile(bl,95):>11.3f}"
              f"{bl.max():>11.3f}{(bl>0.6).mean()*100:>9.1f}%{np.median(jw):>9.3f}"
              f"{np.percentile(jw,95):>9.3f}{jw.max():>9.3f}")
        sheets[name] = ([(bl[i], eye_c[i]) for i in np.argsort(-bl)[:3]],
                        [(jw[i], mouth_c[i]) for i in np.argsort(-jw)[:3]])
    # 拼图：左3列=闭眼最高的3帧(眼部)，右3列=张嘴最大的3帧(嘴部)
    rows=[]
    for name,_ in PICKS:
        if name not in sheets: continue
        e = [c for _,c in sheets[name][0] if c is not None]
        m = [c for _,c in sheets[name][1] if c is not None]
        if len(e)>=3 and len(m)>=3: rows.append((name, e[:3], m[:3]))
    if rows:
        cw,ch=360,140
        s=np.full((len(rows)*(ch+22), 6*cw,3),30,np.uint8)
        for r,(name,e,m) in enumerate(rows):
            y=r*(ch+22)
            cv2.putText(s,f"{name}   | 左3=eyeBlink 峰值帧(眼部)     右3=jawOpen 峰值帧(嘴部)",
                        (6,y+15),cv2.FONT_HERSHEY_SIMPLEX,0.42,(255,255,255),1,cv2.LINE_AA)
            for c,img in enumerate(e+m):
                s[y+22:y+22+ch, c*cw:(c+1)*cw]=img
            cv2.line(s,(3*cw,y+22),(3*cw,y+22+ch),(0,0,255),2)
        cv2.imwrite(str(ROOT/"_scratch"/"_blink_yawn.png"), s)
        print(f"\n拼图 -> _scratch/_blink_yawn.png")
    sys.stdout.flush(); sys.stderr.flush(); os._exit(0)

main()
