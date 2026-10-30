"""Extend existing unittest workflow with grouped-rule scenarios; no accuracy claims."""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from fusion_v2 import FusionV2


def sample(t,**changes):
    s=dict(timestamp=t,legacy_level=0,face_valid=True,pose_valid=True,pose_timestamp=t,
           pose_fatigue_prob=.01,ear=.3,ear_norm=1.,mar=.1,perclos=.05,face_span=30,
           pitch=0.,yaw=0.,roll=0.,head_swing=0.,lr_prob=.1,lr_level=0,
           lr_warmup=False,lr_valid=True,lr_valid_count=450,
           yolo=dict(sample_timestamp=t,eye_left_open_prob=.99,eye_right_open_prob=.99,
                     eye_left_status='open',eye_right_status='open',yawn_probability=.01,yawn_status='inactive'))
    s.update(changes)
    return s

class FusionTests(unittest.TestCase):
    def test_ui_uses_selected_v2_risk_instead_of_legacy_probabilities(self):
        from ui.state import State
        for level,name in enumerate(['normal','mild','moderate','severe']):
            state=State(l_fused=3,l1=3,perclos=.9,p_fat=.99)
            state.fusion_v2=dict(mode='v2',final_level=level,risk_reasons=['selected evidence'])
            state.derive({})
            self.assertEqual(state.level,level)
            self.assertEqual(state.severity,name)
            self.assertEqual(state.l1,3)  # raw model diagnosis retained

    def test_session_exception_keeps_legacy_and_reports_invalid(self):
        import config as C
        from fusion_session import FusionSession
        from ui.state import State
        with patch.object(C,'FUSION_MODE','legacy'),patch.object(C,'FUSION_LOG',''):
            session=FusionSession()
            state=State(l_fused=2)
            result=session.fallback(state,1.,RuntimeError('injected integration fault'))
        self.assertEqual(state.l_fused,2)
        self.assertEqual(result['final_level'],2)
        self.assertEqual(result['degradation_reasons'],['fusion_exception'])
        self.assertFalse(result['eye_evidence']['valid'])
    def run_series(self,seconds,change):
        engine=FusionV2(); outputs=[]
        for i in range(int(seconds*10)+1):
            s=sample(i/10); change(s); outputs.append(engine.update(s))
        return engine,outputs

    def test_normal_and_blink(self):
        engine=FusionV2()
        for i in range(20):
            s=sample(i/10)
            if 5<=i<=6:
                s['ear_norm']=.3;s['yolo'].update(eye_left_open_prob=.01,eye_right_open_prob=.01)
            self.assertEqual(engine.update(s)['level'],0)

    def test_sustained_consensus_closure_escalates(self):
        def change(s):
            s['ear_norm']=.3;s['yolo'].update(eye_left_open_prob=.01,eye_right_open_prob=.01)
        _,out=self.run_series(4,change)
        self.assertIn(2,[x['level'] for x in out]);self.assertEqual(out[-1]['level'],3)

    def test_ear_yolo_conflict_not_added(self):
        _,out=self.run_series(4,lambda s:s.update(ear_norm=.3))
        self.assertEqual(out[-1]['level'],0);self.assertIn('eye',out[-1]['conflicts'])

    def test_yawn_capped_and_short_speech_rejected(self):
        def change(s):
            s['mar']=.8;s['yolo']['yawn_probability']=.99
        _,short=self.run_series(.8,change);self.assertEqual(short[-1]['level'],0)
        _,long=self.run_series(4,change);self.assertEqual(long[-1]['level'],1)

    def test_mar_conflict_and_yolo_invalid(self):
        def change(s):
            s['yolo']['yawn_probability']=.99
        _,out=self.run_series(4,change)
        self.assertIn('mouth',out[-1]['conflicts']);self.assertEqual(out[-1]['level'],0)
        s=sample(0,yolo={},legacy_level=2)
        self.assertEqual(FusionV2().update(s)['level'],2)

    def test_face_lost_stale_future_and_partial(self):
        for changes in [dict(face_valid=False),dict(yolo={}),dict(lr_warmup=True)]:
            out=FusionV2().update(sample(2,**changes))
            if changes.get('face_valid') is False:self.assertFalse(out['eye_evidence']['valid'])
            if changes.get('lr_warmup'):self.assertFalse(out['face_evidence']['valid'])
        for stamp in [0.,3.]:
            s=sample(2);s['yolo']['sample_timestamp']=stamp
            self.assertTrue(FusionV2().update(s)['degraded'])
        s=sample(0);s['yolo']['eye_left_open_prob']=None
        out=FusionV2().update(s);self.assertFalse(out['eye_evidence']['yolo_valid'])
        self.assertFalse(out['degraded'])

    def test_head_quick_glance_vs_sustained(self):
        def change(s):s.update(head_swing=15.,pose_fatigue_prob=.99)
        _,brief=self.run_series(1,change);self.assertLess(brief[-1]['level'],3)
        _,long=self.run_series(4,change);self.assertEqual(long[-1]['level'],3)

    def test_downgrade_hysteresis(self):
        def change(s):
            s['ear_norm']=.3;s['yolo'].update(eye_left_open_prob=.01,eye_right_open_prob=.01)
        engine,out=self.run_series(4,change)
        self.assertEqual(engine.update(sample(4.1))['level'],3)
        self.assertEqual(engine.update(sample(4.4))['level'],3)
        for i in range(45,62):result=engine.update(sample(i/10))
        self.assertEqual(result['level'],0)

    def test_lr_warmup_and_correlated_signals_not_double_counted(self):
        _,out=self.run_series(3,lambda s:s.update(lr_level=2,lr_prob=.99,lr_warmup=True))
        self.assertEqual(out[-1]['level'],0)
        self.assertTrue(out[-1]['face_evidence']['warmup'])
        _,out=self.run_series(3,lambda s:s.update(lr_level=1,lr_prob=.7,perclos=.2))
        self.assertEqual(out[-1]['level'],1)

    def test_multiple_groups_and_pose_conflict(self):
        def change(s):
            s.update(perclos=.2,mar=.8);s['yolo']['yawn_probability']=.99
        _,out=self.run_series(3,change);self.assertEqual(out[-1]['level'],2)
        _,out=self.run_series(4,lambda s:s.update(pose_fatigue_prob=.99))
        self.assertIn('pose_head',out[-1]['conflicts']);self.assertLess(out[-1]['level'],3)

    def test_exact_fallback_all_levels_and_no_false_normal(self):
        for level in range(4):
            out=FusionV2().update(sample(0,yolo={},legacy_level=level,face_valid=False,pose_valid=False))
            self.assertEqual(out['level'],level);self.assertEqual(out['valid_sources'],[])

    def test_left_right_asymmetry(self):
        s=sample(0);s['yolo']['eye_left_open_prob']=.01
        out=FusionV2().update(s)
        self.assertIn('eye',out['conflicts']);self.assertEqual(out['level'],0)

    def test_brief_dashboard_turn_and_forward_surrogates(self):
        # Feature scenarios only, not labelled natural driving videos.
        for changes in [dict(head_swing=15.,pitch=20.),dict(yaw=40.),dict(pose_fatigue_prob=.99,pitch=10.)]:
            _,out=self.run_series(.8,lambda s:s.update(changes))
            self.assertEqual(out[-1]['level'],0)

    def test_missing_mouth_and_pose_staleness(self):
        s=sample(2);s['yolo']['yawn_probability']=None;s['pose_timestamp']=0.
        out=FusionV2().update(s)
        self.assertFalse(out['mouth_evidence']['yolo_valid'])
        self.assertTrue(out['transformer_evidence']['stale'])
        self.assertFalse(out['transformer_evidence']['valid'])

if __name__=='__main__':unittest.main()
