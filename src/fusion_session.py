"""Camera integration and mode control; legacy CSV/formulas stay untouched."""
import json
import hashlib
from dataclasses import asdict
import math
import threading
import time
from pathlib import Path
import config as C
from fusion_v2 import FusionV2, FusionPolicy, finite


def clean(value):
    if isinstance(value,dict):return {k:clean(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [clean(v) for v in value]
    if isinstance(value,float) and not math.isfinite(value):return None
    return value


class FusionSession:
    def __init__(self):
        self.engine=FusionV2(FusionPolicy(**C.FUSION_V2_POLICY))
        self.mode=C.FUSION_MODE
        self.allowed=False
        if C.FUSION_V2_ALLOWED:
            try:
                report=json.loads((C.ROOT/'docs/validation/fusion_v2_report.json').read_text(encoding='utf-8'))
                digest=hashlib.sha256((C.ROOT/'src/fusion_v2.py').read_bytes()).hexdigest()
                self.allowed=(report.get('basic_acceptance_passed') is True and
                              report.get('policy_source_sha256')==digest and
                              report.get('policy')==asdict(self.engine.policy))
            except (OSError,ValueError):pass
        self.lock=threading.Lock()
        self.log_error=None
        self.set_mode(self.mode)

    def set_mode(self,mode):
        if mode not in ('legacy','v2'):raise ValueError('模式必须是 legacy 或 v2')
        if mode=='v2' and not self.allowed:raise PermissionError('后端未开放 V2 切换')
        with self.lock:self.mode=mode
        return dict(mode=mode,switch_allowed=self.allowed,effective='next_decision')

    def fallback(self,state,now,error):
        # A new fusion implementation failure must not stop the proven Legacy source.
        self.engine=FusionV2(FusionPolicy(**C.FUSION_V2_POLICY))
        sample=dict(timestamp=now,legacy_level=state.l_fused,face_valid=False,pose_valid=False,yolo={})
        payload=self.engine.update(sample)
        with self.lock:mode=self.mode
        payload.update(mode=mode,final_level=state.l_fused,last_update_wall=time.time(),
            switch_allowed=False,runtime={},input_features=sample,
            risk_reasons=[f'Fusion V2 异常，退回 Legacy：{type(error).__name__}'],
            degradation_reasons=['fusion_exception'],log_error=str(error))
        state.fusion_v2=payload;state.yolo=None
        if C.FUSION_LOG:
            try:
                path=Path(C.FUSION_LOG);path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('a',encoding='utf-8') as stream:stream.write(json.dumps(payload,ensure_ascii=False,allow_nan=False)+'\n')
            except OSError:pass
        return payload

    def update(self,owner,state,d,lm,probs,stats,eye_sec,head_swing,runtime,now=None):
        now=state.t if now is None else now
        stats=stats or {}
        ts,ears,mars,pitches=owner.fb.arrays()
        count=int(sum(math.isfinite(float(e)) and math.isfinite(float(p)) for e,p in zip(ears,pitches)))
        en=stats.get('en_now')
        if not finite(en) and len(ts)>=3:
            from face import norm_by_time,ROLL_WIN
            import numpy as np
            normalized=ears/np.maximum(norm_by_time(ts,ears,ROLL_WIN),1e-6)
            en=float(normalized[-1])
        y=owner.face.shadow_latest or {}
        sample=clean(dict(timestamp=now,legacy_level=state.l_fused,face_valid=d is not None,
            pose_valid=lm is not None,pose_timestamp=now if lm is not None else None,
            pose_fatigue_prob=float(probs[C.CLASSES.index('fatigue')]),pose_warmup=False,
            pose_class=C.CLASSES[int(probs.argmax())],pose_level=state.l1,
            ear=state.ear,ear_norm=en,mar=state.mar,perclos=stats.get('perclos'),
            brate=stats.get('brate'),face_span=owner.fb.span,geometry_closed_duration=eye_sec,
            pitch=state.pitch,yaw=(d or {}).get('yaw'),roll=(d or {}).get('roll'),
            head_swing=head_swing,nod=stats.get('nod'),lr_prob=state.p_fat,lr_level=state.l2,
            lr_warmup=not owner.fb.full(),lr_valid=state.gate and state.p_fat is not None,
            lr_valid_count=count,yolo=y))
        payload=self.engine.update(sample)
        with self.lock:mode=self.mode
        payload['v2_risk_reasons']=list(payload['risk_reasons'])
        payload['legacy_source']=state.src
        payload['legacy_reasons']=[f'原版融合 L{state.l_fused}，来源：{state.src or "pose"}']
        if mode=='legacy':payload['risk_reasons']=payload['legacy_reasons']
        payload['v2_level_change_reason']=payload['level_change_reason']
        payload['level_change_reason']='；'.join(payload['risk_reasons'])
        payload.update(mode=mode,final_level=state.l_fused if mode=='legacy' else payload['level'],
            switch_allowed=self.allowed,runtime=clean(runtime),last_update_wall=time.time(),
            input_features=sample,log_error=self.log_error)
        for name,entry in payload['runtime'].items():
            entry.update(confidence=None,stale=False,warmup=False)
        payload['runtime']['transformer']['confidence']=sample['pose_fatigue_prob']
        for name,key,backend in [('yolo_eye','eye_evidence','eye_backend'),('yolo_mouth','mouth_evidence','mouth_backend')]:
            group=payload[key]
            payload['runtime'][name]=dict(valid=group['yolo_valid'],confidence=group['confidence'],
                timestamp=group['source_timestamp'],stale=group['yolo_stale'],warmup=False,
                latency_ms=group['latency_ms'],backend=y.get(backend,'unavailable'))
        payload['runtime']['face_branch']=dict(payload['face_evidence'],backend='logistic_regression',
            latency_ms=runtime.get('face_branch',{}).get('latency_ms') if payload['face_evidence']['valid'] else None)
        state.yolo=clean(dict(eye_left_open_prob=payload['eye_evidence']['left_open_prob'],
            eye_right_open_prob=payload['eye_evidence']['right_open_prob'],
            eye_left_closed_prob=1-payload['eye_evidence']['left_open_prob'] if payload['eye_evidence']['left_open_prob'] is not None else None,
            eye_right_closed_prob=1-payload['eye_evidence']['right_open_prob'] if payload['eye_evidence']['right_open_prob'] is not None else None,
            eye_left_state=payload['eye_evidence']['left_state'],eye_right_state=payload['eye_evidence']['right_state'],
            mouth_yawn_prob=payload['mouth_evidence']['yawn_probability'],
            mouth_no_yawn_prob=1-payload['mouth_evidence']['yawn_probability'] if payload['mouth_evidence']['yawn_probability'] is not None else None,
            mouth_state=payload['mouth_evidence']['state'],eye_valid=payload['eye_evidence']['yolo_valid'],
            mouth_valid=payload['mouth_evidence']['yolo_valid'],eye_latency_ms=y.get('eye_latency_ms'),
            mouth_latency_ms=y.get('mouth_latency_ms'),timestamp=y.get('sample_timestamp'),
            stale=payload['eye_evidence']['yolo_stale']))
        # mode is the selected policy; level keeps V2's independent comparator result.
        if mode=='v2':state.l_fused=payload['final_level']
        state.fusion_v2=payload
        if C.FUSION_LOG:
            try:
                path=Path(C.FUSION_LOG);path.parent.mkdir(parents=True,exist_ok=True)
                with path.open('a',encoding='utf-8') as stream:
                    stream.write(json.dumps(clean(payload),ensure_ascii=False,allow_nan=False)+'\n')
            except OSError as exc:self.log_error=str(exc)
        return payload
