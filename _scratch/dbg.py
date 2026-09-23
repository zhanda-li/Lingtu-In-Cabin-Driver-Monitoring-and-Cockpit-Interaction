import sys
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
cap=cv2.VideoCapture(str(C.DATA_RAW/"fatigue"/"fatigue_16.mp4"))
ok,fr=cap.read(); cap.release()
print("read ok:", ok, "shape:", None if fr is None else fr.shape)
res=lm.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,
        data=np.ascontiguousarray(cv2.cvtColor(fr,cv2.COLOR_BGR2RGB))), 0)
print("landmarks:", 0 if not res.face_landmarks else len(res.face_landmarks[0]))
print("blendshapes:", 0 if not res.face_blendshapes else len(res.face_blendshapes[0]))
L=res.face_landmarks[0]; h,w=fr.shape[:2]
for nm,pts in [("EYE",[33,133,362,263,468,473]),("MOUTH",[13,14,61,291])]:
    px=[(int(L[i].x*w),int(L[i].y*h)) for i in pts]
    xs=[p[0] for p in px]; ys=[p[1] for p in px]
    print(f"  {nm} px={px}  span_x={max(xs)-min(xs)} span_y={max(ys)-min(ys)}")
sys.stdout.flush(); sys.stderr.flush()
