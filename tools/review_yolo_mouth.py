"""Summarize visually inspected YawDD intervals; these are not ground-truth labels."""
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def main():
    replay = json.loads((ROOT/'docs/yawdd_shadow_replay.json').read_text(encoding='utf-8'))
    intervals = []
    for start,end,note in [(0,3,'Visible smile/teeth in sampled frames'),
                           (20,23,'Varying mouth poses and a smile in sampled frames'),
                           (54,58,'Sustained wide mouth opening, qualitatively consistent with yawning')]:
        rows = [r for r in replay['rows'] if start<=r['timestamp']<=end]
        if not rows or any(r['mar'] is None or r['yawn_probability'] is None for r in rows):
            raise ValueError('Review interval contains missing evidence')
        intervals.append(dict(start=start,end=end,visual_note=note,samples=len(rows),
            max_smoothed_yawn_probability=max(r['yawn_probability'] for r in rows),
            max_mar=max(r['mar'] for r in rows),
            candidate_times=[r['timestamp'] for r in rows if r['yawn_event']=='yawn_candidate']))
    report = dict(source=replay['video'],review='Contact sheets reviewed at selected 1-second timestamps',
        limitation='No audio review or reliable speech/laughter/singing frame labels. No false-positive rate, sensitivity or accuracy can be inferred.',intervals=intervals)
    (ROOT/'docs/yolo_mouth_qualitative_review.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))

if __name__ == '__main__':
    main()
