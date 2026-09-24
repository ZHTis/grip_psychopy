"""Pre-task zero/MVC acquisition and a self-contained experiment setup record.

All values are sensor voltage or abs(voltage * gain), not calibrated force units.
"""
import copy
import hashlib
import json
import math
import statistics
import time


DEFAULTS = dict(enabled=True, zero_s=5.0, squeeze_s=1.0, rest_s=30.0,
                min_samples=5, max_gap_s=.3, min_range=.01,
                lift_mode='keep', target_fraction=.2, font='auto')


class CalibrationAborted(Exception):
    pass


def settings(config):
    c = {**DEFAULTS, **config.get('calibration', {})}
    for key in ('zero_s', 'squeeze_s', 'rest_s', 'max_gap_s', 'min_range'):
        if not isinstance(c[key], (int, float)) or not math.isfinite(c[key]) or c[key] <= 0:
            raise ValueError(f'calibration.{key} must be finite and positive')
    if type(c['enabled']) is not bool:
        raise ValueError('calibration.enabled must be boolean')
    if type(c['min_samples']) is not int or c['min_samples'] < 2:
        raise ValueError('calibration.min_samples must be an integer >= 2')
    gain = config['grip']['gain']
    if not math.isfinite(gain) or gain == 0:
        raise ValueError('grip.gain must be finite and nonzero')
    if c['lift_mode'] not in ('keep', 'target_fraction'):
        raise ValueError('calibration.lift_mode must be keep or target_fraction')
    if not isinstance(c['target_fraction'], (int, float)) or not 0 < c['target_fraction'] <= 1:
        raise ValueError('calibration.target_fraction must be in (0, 1]')
    if c['lift_mode'] == 'target_fraction' and config['task']['gravity'] <= 0:
        raise ValueError('Positive gravity is required for target_fraction mode')
    return c


def summarize_segment(segment, c):
    samples = segment['samples']
    if len(samples) < c['min_samples']:
        raise ValueError(f"{segment['phase']}: too few fresh samples ({len(samples)})")
    times = [s['t'] for s in samples]
    values = [abs(s['raw']) for s in samples]
    if not all(math.isfinite(v) for v in times + values + [s['voltage'] for s in samples]):
        raise ValueError('Non-finite calibration sample')
    if times != sorted(times) or any(not segment['start_s'] <= t < segment['end_s'] for t in times):
        raise ValueError('Calibration samples fall outside their measurement window')
    gaps = [times[0]-segment['start_s'], segment['end_s']-times[-1]]
    gaps.extend(b-a for a, b in zip(times, times[1:]))
    if max(gaps) > c['max_gap_s']:
        raise ValueError(f"{segment['phase']}: data gap {max(gaps):.3f}s exceeds calibration limit")
    peak = max(samples, key=lambda s: abs(s['raw']))
    return dict(peak_sample=dict(peak), sample_count=len(samples), median_raw=statistics.median(values),
                mean_raw=statistics.mean(values), std_raw=statistics.pstdev(values),
                peak_raw=max(values), min_raw=min(values),
                mean_voltage=statistics.mean(s['voltage'] for s in samples),
                median_voltage=statistics.median(s['voltage'] for s in samples),
                peak_voltage=max(s['voltage'] for s in samples), max_gap_s=max(gaps))


def reference(segments, config):
    c = settings(config)
    if [s['phase'] for s in segments] != ['zero', 'squeeze_1', 'squeeze_2', 'squeeze_3']:
        raise ValueError('Calibration requires zero and exactly three squeeze measurements')
    stats = [summarize_segment(s, c) for s in segments]
    zero = stats[0]['median_raw']
    peaks = [s['peak_raw'] for s in stats[1:]]
    deltas = [p-zero for p in peaks]
    threshold = max(c['min_range'], 5*stats[0]['std_raw'])
    if any(d <= threshold for d in deltas):
        raise ValueError('Each squeeze must exceed zero by the minimum range and 5x zero noise; recalibrate')
    upper = max(peaks)
    task = config['task']
    lift = task['lift_gain'] if c['lift_mode'] == 'keep' else task['gravity']/c['target_fraction']
    fraction = task['gravity']/lift if lift > 0 else None
    return dict(zero_raw=zero, zero_statistic='median(abs(voltage * gain))',
                zero_summary=stats[0], squeeze_summaries=stats[1:], peaks_raw=peaks,
                peaks_above_zero=deltas, mean_peak_raw=statistics.mean(peaks),
                median_peak_raw=statistics.median(peaks), reference_max_raw=upper,
                reference_range_raw=upper-zero, reference_statistic='max of three peaks',
                minimum_accepted_range=threshold,
                configured_lift_gain=task['lift_gain'], effective_lift_gain=lift,
                lift_mode=c['lift_mode'], equilibrium_fraction=fraction,
                equilibrium_reachable=fraction is not None and 0 <= fraction <= 1,
                equilibrium_raw=zero+fraction*(upper-zero) if fraction is not None else None,
                reference_lift_gains=[{'fraction': f, 'lift_gain': task['gravity']/f}
                                      for f in (.1, .2, .3, .5)],
                interpretation='Model reference: lift_gain * normalized_grip = gravity at steady input; not measured force in N/kg')


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


def run_calibration(display, grip, recorder, config, setup):
    c = settings(config)
    result = setup.data['calibration']
    if not c['enabled'] or config['runtime']['headless']:
        result['status'] = 'disabled' if not c['enabled'] else 'skipped_headless'
        setup.save()
        return
    if grip is None:
        result.update(status='error', exit_reason='Calibration requires a working grip reader')
        setup.save()
        raise RuntimeError(result['exit_reason'])
    # Capture every acquired line, rather than sampling the most recent value per frame.
    schedule = [('zero', c['zero_s']), ('squeeze_1', c['squeeze_s']),
                ('rest_1', c['rest_s']), ('squeeze_2', c['squeeze_s']),
                ('rest_2', c['rest_s']), ('squeeze_3', c['squeeze_s'])]
    simulated_low = config['task']['grip_min']/abs(config['grip']['gain'])
    simulated_high = config['task']['grip_max']/abs(config['grip']['gain'])
    result['status'] = 'running'
    setup.save()
    try:
        # Allow serial reset/startup before opening the zero measurement window.
        deadline = recorder.now()+5
        while True:
            if 'escape' in display.event.getKeys():
                raise CalibrationAborted()
            if grip.simulate:
                grip.simulated_voltage = simulated_low
            display.draw_calibration('正在准备 请勿触碰', '正在等待传感器数据', 0)
            display.win.flip()
            try:
                grip.latest(max_age=c['max_gap_s'])
                break
            except RuntimeError:
                if grip.error or recorder.now() >= deadline:
                    raise RuntimeError('No fresh grip data for calibration; check the sensor')
        for phase, duration in schedule:
            is_rest = phase.startswith('rest')
            trial = int(phase[-1]) if phase != 'zero' else 0
            title = '正在准备 请勿触碰' if phase == 'zero' else (
                '请松开握力器 休息' if is_rest else '最大力度握紧')
            detail = '零点采集' if phase == 'zero' else f'第 {trial} / 3 次'
            segment = dict(phase=phase, samples=[])
            recorder.set_context(trial=0, block=0, phase='calibration_'+phase)
            def begin():
                segment['start_s'] = recorder.now()
                segment['end_s'] = segment['start_s']+duration
                if not is_rest:
                    grip.start_capture()
                recorder.record('event', {'name': 'calibration_'+phase+'_start', 'calibration_trial': trial,
                                          'timing': 'callOnFlip', 'duration_s': duration})
            display.draw_calibration(title, detail, 0)
            display.win.callOnFlip(begin)
            display.win.flip()
            if not is_rest:
                result['segments'].append(segment)
            last_save = recorder.now()
            try:
                while recorder.now() < segment['end_s']:
                    if 'escape' in display.event.getKeys():
                        raise CalibrationAborted()
                    if grip.error:
                        raise RuntimeError('Grip reader failed during calibration') from grip.error
                    if grip.simulate:
                        grip.simulated_voltage = simulated_high if (
                            phase.startswith('squeeze') and display.mouse.getPressed()[0]) else simulated_low
                    if not is_rest:
                        segment['samples'].extend(grip.drain_capture())
                    elapsed = recorder.now()-segment['start_s']
                    remaining = max(0, duration-elapsed)
                    display.draw_calibration(title, f'{detail}\n剩余 {remaining:.1f} 秒', elapsed/duration)
                    display.win.flip()
                    if recorder.now()-last_save >= .25:
                        recorder.flush()
                        setup.save()
                        last_save = recorder.now()
            finally:
                if not is_rest:
                    segment['samples'].extend(grip.stop_capture())
                    segment['samples'] = [s for s in segment['samples']
                                          if segment['start_s'] <= s['t'] < segment['end_s']]
                    segment['observed_end_s'] = recorder.now()
                    setup.save()
            recorder.record('event', {'name': 'calibration_'+phase+'_end', 'calibration_trial': trial})
            if not is_rest:
                segment['summary'] = summarize_segment(segment, c)
                setup.save()
        values = reference(result['segments'], config)
        result.update(status='complete', reference=values)
        config['task'].update(grip_min=values['zero_raw'], grip_max=values['reference_max_raw'],
                              lift_gain=values['effective_lift_gain'])
        setup.save()
        recorder.record('event', {'name': 'calibration_complete', 'reference': values})
        recorder.flush()
        display.event.clearEvents()
        while True:
            keys = display.event.getKeys()
            if 'escape' in keys:
                raise CalibrationAborted()
            if 'space' in keys:
                break
            peaks = ' / '.join(f'{p:.4f}' for p in values['peaks_raw'])
            fraction = values['equilibrium_fraction']
            balance = f'{fraction:.1%}' if fraction is not None else '不可计算'
            display.draw_calibration('校准完成 请松开握力器',
                f"零点 {values['zero_raw']:.4f}\n三次峰值 {peaks}\n"
                f"参考最大值 {values['reference_max_raw']:.4f}\n"
                f"lift_gain = {values['effective_lift_gain']:.2f}   理论平衡握力 {balance}\n"
                f"参考 lift_gain：20% → {config['task']['gravity']/.2:.1f}；30% → {config['task']['gravity']/.3:.1f}\n"
                '数值为传感器读数，非牛顿/公斤\n按空格开始实验，Esc 退出', 1)
            display.win.flip()
    except BaseException as exc:
        if result['status'] != 'complete':
            result['status'] = 'aborted' if isinstance(exc, CalibrationAborted) else 'error'
        result['exit_reason'] = type(exc).__name__ + ': ' + str(exc)
        setup.save()
        raise
