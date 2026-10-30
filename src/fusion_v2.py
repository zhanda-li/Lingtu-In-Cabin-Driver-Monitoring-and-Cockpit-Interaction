"""Explainable grouped evidence; Legacy inputs/weights are never rewritten.

Scores are ordinal risk levels, not calibrated fatigue probabilities. Persistence
defaults reuse project durations; the V2 combinations remain provisional policy.
"""
from collections import deque
from dataclasses import dataclass
import math
import config as C
from face import BLINK_THR, YAWN_THR, YAWN_MIN, CLOSE_EYE_SEC, HEAD_DEG, NOD_MIN, ROLL_WIN


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class FusionPolicy:
    # These agree with the verified YOLO shadow classifier and original time constants.
    eye_closed_probability: float = .7
    yawn_probability: float = .8
    max_age: float = .5
    eye_seconds: float = CLOSE_EYE_SEC
    mouth_seconds: float = max(YAWN_MIN, 1.5)  # established shadow duration
    severe_seconds: float = C.WINDOW / C.TARGET_FPS
    head_degrees: float = HEAD_DEG
    enter_seconds: float = .5       # fuse.B2_ENTER_SEC
    exit_seconds: float = 1.5       # fuse.B2_EXIT_SEC
    perclos_mild: float = .187      # existing ui.state severity defaults
    perclos_moderate: float = .426
    pose_probability: float = .60   # live.ENTER_TH

    def __post_init__(self):
        if not 0.5<self.eye_closed_probability<1 or not 0.5<self.yawn_probability<1:
            raise ValueError('Classification thresholds must be between .5 and 1')
        if not 0<=self.perclos_mild<=self.perclos_moderate<=1:
            raise ValueError('Invalid PERCLOS thresholds')
        if min(self.max_age,self.eye_seconds,self.mouth_seconds,self.severe_seconds,self.head_degrees)<=0 or min(self.enter_seconds,self.exit_seconds)<0:
            raise ValueError('Invalid persistence settings')


class FusionV2:
    def __init__(self, policy=None):
        self.policy = policy or FusionPolicy()
        self.level = 0
        self.pending = None
        self.last = None
        self.starts = {}
        self.mouth_count = 0
        self.mouth_fired = False
        self.events = deque(maxlen=20)

    def hold(self, name, active, now):
        if not active:
            self.starts.pop(name, None)
            return 0.
        self.starts.setdefault(name, now)
        return max(0., now-self.starts[name])

    def group(self, valid, now, *, level=0, state='normal', confidence=None,
              stale=False, warmup=False, reasons=(), **extra):
        return dict(valid=bool(valid), confidence=confidence, timestamp=now,
                    stale=bool(stale), warmup=bool(warmup), level=int(level),
                    state=state if valid else ('stale' if stale else 'warmup' if warmup else 'invalid'),
                    reasons=list(reasons), **extra)

    def update(self, sample):
        p = self.policy
        now = sample['timestamp']
        if not finite(now):
            raise ValueError('Fusion timestamp must be finite')
        if self.last is not None and (now<=self.last or now-self.last>p.max_age):
            self.starts.clear(); self.pending=None; self.mouth_fired=False
        self.last = now
        face = bool(sample.get('face_valid'))
        y = sample.get('yolo') or {}
        stamp = y.get('sample_timestamp')
        stale = finite(stamp) and not 0<=now-stamp<=p.max_age
        fresh = face and finite(stamp) and not stale and not y.get('pending', False)
        left, right = y.get('eye_left_open_prob'), y.get('eye_right_open_prob')
        left_valid = fresh and finite(left) and 0<=left<=1 and y.get('eye_left_status')!='invalid'
        right_valid = fresh and finite(right) and 0<=right<=1 and y.get('eye_right_status')!='invalid'
        eyes_valid = left_valid and right_valid
        mouth_prob = y.get('yawn_probability')
        mouth_valid = fresh and finite(mouth_prob) and 0<=mouth_prob<=1 and y.get('yawn_status')!='invalid'
        en, mar = sample.get('ear_norm'), sample.get('mar')
        geo_eye = face and finite(en)
        geo_mouth = face and finite(mar)
        closed = geo_eye and en<BLINK_THR
        y_closed = eyes_valid and max(left,right)<1-p.eye_closed_probability
        y_open = eyes_valid and min(left,right)>p.eye_closed_probability
        asymmetric = eyes_valid and ((left<.3 and right>.7) or (right<.3 and left>.7))
        eye_conflict = geo_eye and eyes_valid and ((closed and y_open) or (not closed and y_closed) or asymmetric)
        agreement = geo_eye and eyes_valid and (y_closed if closed else y_open)
        eye_duration = self.hold('eye', closed and (y_closed or not eyes_valid), now)
        perclos = sample.get('perclos')
        pc_valid = face and finite(perclos) and sample.get('face_span',0)>=ROLL_WIN
        eye_level = 0
        eye_reasons = []
        if not eye_conflict:
            if eye_duration>=p.eye_seconds:
                eye_level=2; eye_reasons.append('持续闭眼')
            if pc_valid and perclos>=p.perclos_mild:
                eye_level=max(eye_level,1); eye_reasons.append('PERCLOS 趋势升高')
            if pc_valid and perclos>=p.perclos_moderate:
                eye_level=max(eye_level,2)
            if agreement and closed and eye_duration>=p.severe_seconds:
                eye_level=3; eye_reasons.append('几何与 YOLO 一致的严重持续闭眼')
        eye = self.group(geo_eye,now,level=eye_level,
            state='conflict' if eye_conflict else 'closed' if closed else 'open',
            confidence=min(max(left,1-left),max(right,1-right)) if eyes_valid else None,
            warmup=not geo_eye and face, reasons=eye_reasons,
            agreement=agreement, conflict=eye_conflict, closed_duration=eye_duration,
            left_state='invalid' if not left_valid else 'closed' if left<.3 else 'open' if left>.7 else 'uncertain',
            right_state='invalid' if not right_valid else 'closed' if right<.3 else 'open' if right>.7 else 'uncertain',
            left_open_prob=left if left_valid else None,right_open_prob=right if right_valid else None,
            ear=sample.get('ear') if face else None,perclos=perclos if pc_valid else None,
            yolo_valid=eyes_valid,yolo_stale=stale,latency_ms=y.get('eye_latency_ms'))
        eye['source_timestamp']=stamp

        mar_open = geo_mouth and mar>YAWN_THR
        y_yawn = mouth_valid and mouth_prob>p.yawn_probability
        mouth_conflict = geo_mouth and mouth_valid and mar_open!=y_yawn
        mouth_duration = self.hold('mouth',mar_open and (y_yawn or not mouth_valid),now)
        mouth_hit = mouth_duration>=p.mouth_seconds and not mouth_conflict
        if mouth_hit and not self.mouth_fired:
            self.mouth_count+=1
            self.events.append(dict(timestamp=now,kind='yawn_candidate',message='持续嘴部候选证据'))
        self.mouth_fired = mouth_hit
        mouth = self.group(geo_mouth,now,level=1 if mouth_hit else 0,
            state='conflict' if mouth_conflict else 'candidate' if mouth_hit else 'observing' if mar_open else 'normal',
            confidence=max(mouth_prob,1-mouth_prob) if mouth_valid else None,
            reasons=['MAR 与嘴部分类持续一致'] if mouth_hit and mouth_valid else ['持续 MAR 候选（YOLO 缺失）'] if mouth_hit else [],
            conflict=mouth_conflict,yolo_valid=mouth_valid,yolo_stale=stale,
            mar=mar if geo_mouth else None,yawn_probability=mouth_prob if mouth_valid else None,
            duration=mouth_duration,event_count=self.mouth_count,latency_ms=y.get('mouth_latency_ms'))
        mouth['source_timestamp']=stamp

        pose_prob = sample.get('pose_fatigue_prob')
        pose_stamp = sample.get('pose_timestamp')
        pose_stale = finite(pose_stamp) and not 0<=now-pose_stamp<=p.max_age
        pose_valid = bool(sample.get('pose_valid')) and finite(pose_prob) and finite(pose_stamp) and 0<=now-pose_stamp<=p.max_age
        pose_duration = self.hold('pose',pose_valid and pose_prob>=p.pose_probability,now)
        transformer = self.group(pose_valid,now,confidence=pose_prob if pose_valid else None,
            level=2 if pose_duration>=p.severe_seconds else 0,
            state='persistent' if pose_duration>=p.severe_seconds else 'observing' if pose_duration else 'normal',
            warmup=bool(sample.get('pose_warmup')),stale=pose_stale,source_timestamp=pose_stamp,duration=pose_duration,
            predicted_class=sample.get('pose_class'),legacy_pose_level=sample.get('pose_level'),
            reasons=['姿态疲劳概率持续超过原进入阈值'] if pose_duration>=p.severe_seconds else [])
        swing = sample.get('head_swing')
        head_valid = face and finite(sample.get('pitch')) and finite(swing)
        head_duration = self.hold('head',head_valid and swing>=p.head_degrees,now)
        head_hit = head_duration>=p.severe_seconds and pose_duration>=p.severe_seconds
        head = self.group(head_valid,now,level=3 if head_hit else 0,
            state='persistent_down' if head_hit else 'observing' if head_duration else 'normal',
            reasons=['持续下探与姿态时序共同支持'] if head_hit else [],duration=head_duration,
            pitch=sample.get('pitch') if face else None,yaw=sample.get('yaw') if face else None,
            roll=sample.get('roll') if face else None,head_swing=swing if head_valid else None,
            nod_rate=sample.get('nod'),nod_event=None,nod_count=None)
        lr = sample.get('lr_prob')
        lr_warmup = bool(sample.get('lr_warmup',True))
        lr_valid = face and not lr_warmup and bool(sample.get('lr_valid')) and finite(lr)
        lr_level = min(2,max(0,int(sample.get('lr_level',0)))) if lr_valid else 0
        face_evidence = self.group(lr_valid,now,level=lr_level,warmup=lr_warmup,
            confidence=lr if lr_valid else None,state='abnormal' if lr_level else 'normal',
            valid_samples=sample.get('lr_valid_count',0),reasons=['原逻辑回归有效投票'] if lr_level else [])
        # FaceBranch and Eye share eye features: take their maximum, never sum.
        eye_family = max(eye_level,lr_level)
        target = max(eye_family,mouth['level'],head['level'],transformer['level'])
        # Independent sustained mouth + eye groups can support L2, never directly L3.
        if eye_family>=1 and mouth_hit:
            target=max(target,2)
        groups=dict(eye=eye,mouth=mouth,head=head,transformer=transformer,face=face_evidence)
        valid_sources=[name for name,g in groups.items() if g['valid']]
        conflicts=[name for name,g in groups.items() if g.get('conflict')]
        if pose_valid and head_valid and pose_duration>=p.severe_seconds and head_duration==0:
            conflicts.append('pose_head')
        reasons=[reason for g in groups.values() if g['valid'] for reason in g['reasons']]
        legacy = int(sample.get('legacy_level',0))
        previous_level=self.level
        # Exact legacy fallback when neither YOLO eye nor mouth can contribute.
        fallback = not eyes_valid and not mouth_valid
        if fallback:
            self.level=legacy; self.pending=None
            reasons=['YOLO 不可用，使用原版融合结果']
        else:
            if target==self.level:
                self.pending=None
            elif self.pending is None or self.pending[0]!=target:
                self.pending=(target,now)
            elif now-self.pending[1]>=(p.enter_seconds if target>self.level else p.exit_seconds):
                self.level=target; self.pending=None
        final = self.level
        if final!=previous_level:
            self.events.append(dict(timestamp=now,kind='level_change',message=f'V2 L{previous_level} → L{final}'))
        if final!=target and not fallback:
            reasons.append('降级滞回保持' if target<final else '升级持续性观察')
        if not valid_sources:
            reasons.append('无有效视觉证据；等级不能解释为确认正常')
        return dict(mode='v2',level=final,confidence=None,confidence_kind='ordinal_rules_not_probability',
            legacy_level=legacy,fusion_v2_level=final,last_update=now,
            risk_reasons=reasons or ['未达到持续证据阈值'],level_change_reason='；'.join(reasons) if reasons else '持续性与降级滞回',
            eye_evidence=eye,mouth_evidence=mouth,head_evidence=head,
            transformer_evidence=transformer,face_evidence=face_evidence,conflicts=conflicts,
            valid_sources=valid_sources,invalid_sources=[n for n in groups if n not in valid_sources],
            degraded=fallback,degradation_reasons=[r for r in ['eye_yolo_unavailable' if not eyes_valid else '',
                                                'mouth_yolo_unavailable' if not mouth_valid else ''] if r],
            target_level=target,trend='up' if target>final else 'down' if target<final else 'stable',
            recent_events=list(self.events))
