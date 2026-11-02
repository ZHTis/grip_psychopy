"""Formal runs require a measured, persisted reference; debug never claims MVC."""
import copy
import hashlib
import json
import math
from pathlib import Path
from uuid import uuid4

from .paths import project_path
from .weights import vector


def configure_mode(config, args):
    debug = bool(getattr(args, 'debug', False) or args.simulate)
    source = getattr(args, 'calibration_file', None)
    if debug and source:
        raise ValueError('--calibration-file cannot be combined with --debug or --simulate')
    c = config.setdefault('calibration', {})
    # Legacy enabled=false is not permission to run an uncalibrated experiment.
    c.update(enabled=not debug, debug_mode=debug, source_file=source)


def identity(device):
    c = device.config
    result = dict(participant=str(c.get('participant', '')), device=device.name)
    if device.name == 'uno':
        result.update(gain=c['grip']['gain'], sensor_serial=c.get('serial_devices', {}).get('grip'))
    else:
        result.update(source_hand=device.source_hand, display_hand=device.display_hand,
                      sensor_serial=c['multichannel'].get('serial_number'))
    return result


def validate_reference(profile, device):
    if profile.get('schema_version') != 1 or profile.get('measured') is not True or not profile.get('calibration_id'):
        raise ValueError('Not a measured calibration_profile.json')
    if profile.get('identity') != identity(device):
        raise ValueError('标定文件的参与者、设备、手别或采集设置不匹配，请重新标定')
    ref = profile['reference']
    if device.name == 'uno':
        values = [ref.get('minimum'), ref.get('maximum')]
        if any(type(v) not in (float, int) or not math.isfinite(v) for v in values) or not 0 <= values[0] < values[1]:
            raise ValueError('Invalid UNO calibration range')
    else:
        vector(ref['baseline_g'], 'baseline_g')
        ranges = vector(ref['reference_ranges_g'], 'reference_ranges_g')
        if max(ranges) <= 0:
            raise ValueError('No valid calibrated channels')
    return profile


def prepare_calibration(device, display, setup):
    c = device.config['calibration']
    device.calibration_id = None
    if c['debug_mode']:
        device.calibrate(display, setup)
        setup.data['calibration'].update(status='debug_skipped', measured=False)
        setup.data['debug_mode'] = True
        setup.save()
        return
    source = c.get('source_file')
    if source:
        path = project_path(source)
        content = path.read_bytes()
        profile = validate_reference(json.loads(content), device)
        ref = profile['reference']
        if device.name == 'uno':
            device.config['task'].update(grip_min=ref['minimum'], grip_max=ref['maximum'])
            device.devices.fallback_raw = ref['minimum']
        else:
            device.model.calibrate(ref['baseline_g'], ref['reference_ranges_g'])
        setup.data['calibration'].update(status='loaded', source_path=str(path),
            source_sha256=hashlib.sha256(content).hexdigest(), measured=True)
    else:
        device.calibrate(display, setup)
        if setup.data['calibration']['status'] != 'complete':
            raise RuntimeError('正式任务必须先完成最大握力标定；调试请使用 --debug')
        if device.name == 'uno':
            t = device.config['task']
            ref = dict(minimum=t['grip_min'], maximum=t['grip_max'])
        else:
            snapshot = device.model.snapshot()
            if not snapshot['calibrated']:
                raise RuntimeError('RX calibration did not produce measured references')
            ref = {k:snapshot[k] for k in ('baseline_g', 'reference_ranges_g')}
        profile = dict(schema_version=1, measured=True, calibration_id=uuid4().hex,
            identity=identity(device), reference=ref, source_session=str(setup.recorder.directory),
            measurements=copy.deepcopy(setup.data['calibration']))
        validate_reference(profile, device)
    # Copy the reference into every session before allowing any task frames.
    path = setup.recorder.directory/'calibration_profile.json'
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(profile, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    tmp.replace(path)
    device.calibration_id = profile['calibration_id']
    setup.data.update(calibration_id=device.calibration_id, calibration_profile=profile, debug_mode=False)
    setup.save()
    device.recorder.record('event', dict(name='calibration_reference_ready', calibration_id=device.calibration_id,
                                        source='loaded' if source else 'measured'))
    device.recorder.flush()
