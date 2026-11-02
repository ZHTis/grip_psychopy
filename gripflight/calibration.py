"""Shared calibration settings and experiment archive; device algorithms live in input_devices."""
import copy
import hashlib
import json
import math


DEFAULTS = dict(enabled=True, zero_s=5.0, squeeze_s=1.0, rest_s=30.0,
                min_samples=5, max_gap_s=.3, squeeze_data_timeout_s=.5, min_range=.01,
                lift_mode='keep', target_fraction=.2, font='auto')


class CalibrationAborted(Exception):
    pass


def settings(config):
    c = {**DEFAULTS, **config.get('calibration', {})}
    for key in ('zero_s', 'squeeze_s', 'rest_s', 'max_gap_s', 'squeeze_data_timeout_s', 'min_range'):
        if not isinstance(c[key], (int, float)) or not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'calibration.{key} must be finite and positive')
    if type(c['enabled']) is not bool:
        raise ValueError('calibration.enabled must be boolean')
    if type(c['min_samples']) is not int or c['min_samples'] < 2:
        raise ValueError('calibration.min_samples must be an integer >= 2')
    if c['lift_mode'] not in ('keep', 'target_fraction'):
        raise ValueError('calibration.lift_mode must be keep or target_fraction')
    if not isinstance(c['target_fraction'], (int, float)) or not 0 < c['target_fraction'] <= 1:
        raise ValueError('calibration.target_fraction must be in (0, 1]')
    if c['lift_mode'] == 'target_fraction' and config['task']['gravity'] <= 0:
        raise ValueError('Positive gravity is required for target_fraction mode')
    return c


class ExperimentSetup:
    def __init__(self, recorder, original, effective, map_bytes, objects):
        if recorder.backend is None:
            raise RuntimeError('Cannot save experiment setup: session storage unavailable')
        self.recorder, self.config = recorder, effective
        self.path = recorder.directory/'experiment_setup.json'
        self.data = dict(schema_version=1, status='initializing',
                         simulated=effective['runtime']['simulate'],
                         original_config=copy.deepcopy(original),
                         map=dict(path=effective['map'], sha256=hashlib.sha256(map_bytes).hexdigest(),
                                  csv_text=map_bytes.decode('utf-8-sig'), objects=objects),
                         calibration=dict(status='pending', settings=settings(effective), segments=[]))
        self.save()

    def save(self):
        self.data['effective_config'] = copy.deepcopy(self.config)
        self.data['lift_gain'] = self.config['task']['lift_gain']
        self.data['updated_host_s'] = self.recorder.now()
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
        tmp.replace(self.path)


# Compatibility imports for existing scripts. The shared runner uses adapters.
def summarize_segment(*args, **kwargs):
    from .input_devices.uno_calibration import summarize_segment as impl
    return impl(*args, **kwargs)


def reference(*args, **kwargs):
    from .input_devices.uno_calibration import reference as impl
    return impl(*args, **kwargs)


def run_calibration(*args, **kwargs):
    from .input_devices.uno_calibration import run_calibration as impl
    return impl(*args, **kwargs)
