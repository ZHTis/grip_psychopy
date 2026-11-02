"""Right-hand 25-channel weighted input. No changes to the legacy UNO path."""
import copy
import json
import math
import threading
from pathlib import Path

# Initial anatomical grouping inferred from manufacturer point diagram (p.6).
# Region boundaries are a project convention, not a manufacturer specification.
REGIONS = [
    ('thumb', '拇指', 20, [1, 6, 11]),
    ('index', '食指', 20, [2, 7, 12, 17]),
    ('middle', '中指', 14, [3, 8, 13, 18]),
    ('ring', '无名指', 13, [4, 9, 14, 19]),
    ('little', '小指', 10, [5, 10, 15, 20]),
    ('thenar', '大鱼际', 20, [16, 21, 22]),
    ('hypothenar', '小鱼际', 3, [23, 24, 25]),
]


def default_weights():
    result = [0.0]*25
    for _, _, total, channels in REGIONS:
        for channel in channels:
            result[channel-1] = total/len(channels)
    return result


def vector(values, name):
    if not isinstance(values, (list, tuple)) or len(values) != 25:
        raise ValueError(name+' requires exactly 25 values')
    if any(type(v) not in (int, float) or not math.isfinite(v) or v < 0 for v in values):
        raise ValueError(name+' values must be finite and nonnegative')
    return list(values)


def validate_profile(profile):
    weights = vector(profile['weights'], 'weights')
    if sum(weights) <= 0 or sum(weights) > 1e6:
        raise ValueError('权重总和必须大于 0 且不超过 1000000')
    for key in ('lift_gain', 'reference_scale'):
        value = profile[key]
        if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 1e6:
            raise ValueError(key+' 必须为正数且不超过 1000000')
    return dict(weights=weights, lift_gain=profile['lift_gain'], reference_scale=profile['reference_scale'])


def evaluate(values_g, snapshot):
    values = vector(values_g, 'values_g')
    weights = snapshot['weights']
    total = sum(weights)
    effective = [w/total for w in weights]
    signal = [max(0, v-b) for v, b in zip(values, snapshot['baseline_g'])]
    contributions = [w*v for w, v in zip(effective, signal)]
    reference = sum(w*r for w, r in zip(effective, snapshot['reference_ranges_g']))*snapshot['reference_scale']
    if reference <= 0 or not math.isfinite(reference):
        raise ValueError('所选通道没有有效参考范围，请先校准或恢复有响应通道的权重')
    weighted = sum(contributions)
    normalized = min(1.0, weighted/reference)
    calibration_reference = sum(w*r for w, r in zip(effective, snapshot['reference_ranges_g']))
    calibrated = snapshot.get('calibrated', False)
    relative = weighted/calibration_reference if calibrated and calibration_reference > 0 else None
    channel_relative = [(v-b)/r if r > 0 else None
                        for v,b,r in zip(values, snapshot['baseline_g'], snapshot['reference_ranges_g'])] if calibrated else [None]*25
    return dict(weighted_g=weighted, reference_g=reference, normalized=normalized,
                absolute_weighted_g=sum(w*v for w,v in zip(effective, values)),
                calibration_reference_g=calibration_reference, relative_calibrated=relative,
                percent_calibrated=100*relative if relative is not None else None,
                channel_relative_calibrated=channel_relative,
                contributions_g=contributions, effective_weights=effective,
                lift=normalized*snapshot['lift_gain'], weight_revision=snapshot['revision'])


class WeightModel:
    def __init__(self, profile, record, profile_path):
        self.lock = threading.RLock()
        self.record, self.profile_path = record, Path(profile_path)
        self.locked = False
        self.data = dict(validate_profile(profile), revision=0, baseline_g=[0.0]*25,
                         reference_ranges_g=[1000.0]*25, calibrated=False)
        self._record(self.data, 'initial')

    def _record(self, snapshot, reason):
        if self.record('weight_update', dict(snapshot, reason=reason)) is None:
            raise RuntimeError('权重记录保存失败，本次修改未生效')

    def snapshot(self):
        with self.lock:
            return copy.deepcopy(self.data)

    def update(self, profile, expected_revision=None, reason='panel'):
        validated = validate_profile(profile)
        with self.lock:
            if self.locked:
                raise ValueError('正在校准，请完成后再调整权重')
            if expected_revision is not None and expected_revision != self.data['revision']:
                raise ValueError('参数已发生变化，请刷新面板后重试')
            candidate = dict(self.data, **validated)
            candidate['revision'] += 1
            evaluate(candidate['baseline_g'], candidate)
            self._record(candidate, reason)
            self.data = candidate
            return self.snapshot()

    def calibrate(self, baseline, ranges):
        baseline, ranges = vector(baseline, 'baseline'), vector(ranges, 'ranges')
        with self.lock:
            candidate = dict(self.data, baseline_g=baseline, reference_ranges_g=ranges,
                             calibrated=True, revision=self.data['revision']+1)
            evaluate(baseline, candidate)
            self._record(candidate, 'calibration')
            self.data = candidate
            return self.snapshot()

    def save_profile(self):
        with self.lock:
            profile = dict(schema_version=1, hand='right',
                           **{key: self.data[key] for key in ('weights', 'lift_gain', 'reference_scale')})
            self.profile_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.profile_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(self.profile_path)
            self._record(self.data, 'save_profile')
            return str(self.profile_path)


class TickClock:
    """Game time independent of device rate. Pauses and long stalls do not burst."""
    def __init__(self, rate, max_backlog=.25):
        self.dt = 1/rate
        self.max_backlog = max_backlog
        self.last = None
        self.pending = 0.0

    def advance(self, now, paused=False):
        if self.last is None:
            self.last = now
            return 0, False
        elapsed = max(0.0, now-self.last)
        self.last = now
        if paused:
            self.pending = 0.0
            return 0, False
        stalled = elapsed > self.max_backlog
        self.pending += min(elapsed, self.dt) if stalled else elapsed
        count = int((self.pending+1e-10)/self.dt)
        self.pending = max(0, self.pending-count*self.dt)
        return count, stalled
