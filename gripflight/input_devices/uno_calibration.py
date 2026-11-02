"""UNO zero/MVC acquisition and its single-channel calibration pages."""
import math
import statistics

from ..calibration import CalibrationAborted, settings
from ..uno_feedback import feedback_scale


def calibration_keys(display):
    keys = display.event.getKeys()
    external_abort = getattr(display, 'abort_requested', lambda: False)
    if 'escape' in keys or external_abort():
        raise CalibrationAborted()
    return keys


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
    limit = c['squeeze_data_timeout_s'] if segment['phase'].startswith('squeeze') else c['max_gap_s']
    if max(gaps) > limit:
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
    simulated_low = config['task']['grip_min']/abs(config['grip']['gain'])
    simulated_high = config['task']['grip_max']/abs(config['grip']['gain'])
    result['status'] = 'running'
    result['attempts'] = []
    baseline = None
    scale = 1.0
    def draw(title, detail, progress, phase='zero', elapsed=0, peaks=None):
        raw = None
        if phase.startswith('squeeze'):
            try:
                raw = grip.latest(max_age=c['squeeze_data_timeout_s'])['raw']
            except RuntimeError:
                pass  # Missing data is unavailable, never substitute a fabricated force.
        display.uno_orb_feedback = dict(phase=phase, raw=raw, baseline=baseline,
                                       scale=scale, elapsed=elapsed, peaks=peaks, host_s=recorder.now())
        display.draw_calibration(title, detail, progress)
    setup.save()
    try:
        # Allow serial reset/startup before opening the zero measurement window.
        deadline = recorder.now()+5
        while True:
            calibration_keys(display)
            if grip.simulate:
                grip.simulated_voltage = simulated_low
            draw('正在准备 请勿触碰', '正在等待传感器数据', 0)
            display.win.flip()
            try:
                grip.latest(max_age=c['max_gap_s'])
                break
            except RuntimeError:
                if grip.error or recorder.now() >= deadline:
                    raise RuntimeError('No fresh grip data for calibration; check the sensor')
        def acquire(phase, duration, attempt=0):
            is_rest = phase.startswith('rest')
            squeezing = phase.startswith('squeeze')
            trial = int(phase.split('_')[1]) if phase != 'zero' else 0
            title = '正在准备 请勿触碰' if phase == 'zero' else (
                '请松开握力器 休息' if is_rest else '最大力度握紧')
            detail = '零点采集' if phase == 'zero' else f'第 {trial} / 3 次'
            segment = dict(phase=phase, samples=[], attempt=attempt, status='running')
            recorder.set_context(trial=0, block=0, phase='calibration_'+phase)
            def begin():
                segment['start_s'] = recorder.now()
                segment['end_s'] = segment['start_s']+duration
                if not is_rest:
                    grip.start_capture()
                recorder.record('event', {'name': 'calibration_'+phase+'_start', 'calibration_trial': trial,
                                          'attempt': attempt, 'timing': 'callOnFlip', 'duration_s': duration})
            draw(title, detail, 0, phase=phase)
            display.win.callOnFlip(begin)
            display.win.flip()
            if not is_rest:
                result['segments'].append(segment)
            if squeezing:
                result['attempts'].append(segment)
            last_save = recorder.now()
            last_fresh = segment['start_s']
            invalid = None
            try:
                while recorder.now() < segment['end_s']:
                    calibration_keys(display)
                    if grip.error:
                        raise RuntimeError('Grip reader failed during calibration; reconnect and restart') from grip.error
                    if grip.simulate:
                        grip.simulated_voltage = simulated_high if (
                            squeezing and display.mouse.getPressed()[0]) else simulated_low
                    if not is_rest:
                        incoming = grip.drain_capture()
                        segment['samples'].extend(incoming)
                        # Only newly acquired, time-advancing samples reset the watchdog.
                        for sample in incoming:
                            t = sample['t']
                            if segment['start_s'] <= t <= recorder.now() and t > last_fresh:
                                if squeezing and t-last_fresh > c['squeeze_data_timeout_s']:
                                    invalid = 'data_timeout'
                                last_fresh = t
                        if squeezing and recorder.now()-last_fresh > c['squeeze_data_timeout_s']:
                            invalid = 'data_timeout'
                        if invalid:
                            segment['stopped_s'] = recorder.now()
                            break
                    elapsed = recorder.now()-segment['start_s']
                    remaining = max(0, duration-elapsed)
                    cue_detail = detail if squeezing else f'{detail}\n剩余 {remaining:.1f} 秒'
                    draw(title, cue_detail, elapsed/duration, phase=phase, elapsed=elapsed)
                    display.win.flip()
                    if recorder.now()-last_save >= .25:
                        recorder.flush()
                        setup.save()
                        last_save = recorder.now()
            except BaseException:
                segment['status'] = 'interrupted'
                raise
            finally:
                if not is_rest:
                    segment['samples'].extend(grip.stop_capture())
                    cutoff = min(segment['end_s'], segment.get('stopped_s', recorder.now()))
                    segment['samples'] = [s for s in segment['samples']
                                          if segment['start_s'] <= s['t'] < cutoff]
                    segment['observed_end_s'] = recorder.now()
                    setup.save()
            if not is_rest and not invalid:
                try:
                    segment['summary'] = summarize_segment(segment, c)
                    if squeezing:
                        threshold = max(c['min_range'], 5*result['segments'][0]['summary']['std_raw'])
                        if segment['summary']['peak_raw']-baseline <= threshold:
                            invalid = 'no_valid_contraction'
                except ValueError as exc:
                    if not squeezing:
                        raise
                    invalid = str(exc)
            segment['status'] = 'invalid' if invalid else 'valid'
            if invalid:
                segment['invalid_reason'] = invalid
                result['segments'].remove(segment)
            recorder.record('event', {'name': 'calibration_'+phase+'_end', 'calibration_trial': trial,
                                      'attempt': attempt, 'status': segment['status'], 'reason': invalid})
            setup.save()
            return segment

        zero = acquire('zero', c['zero_s'])
        baseline = zero['summary']['median_raw']
        scale = feedback_scale(baseline, config['grip']['gain'])
        result['feedback_ui'] = dict(kind='live_orb', baseline=baseline, scale=scale,
            prepare_color='gray', squeeze_color='red', rest_color='gray', release_s=.8,
            title_feedback='effort-scaled during squeeze; smaller static gray during rest',
            formula='delta/(delta+scale); same scale for all three squeezes; not MVC percent')
        setup.save()
        for trial in range(1, 4):
            attempt = 0
            while True:
                attempt += 1
                measured = acquire(f'squeeze_{trial}', c['squeeze_s'], attempt)
                if measured['status'] == 'valid':
                    if trial < 3:
                        acquire(f'rest_{trial}', c['rest_s'])
                    break
                # Failed attempts remain in attempts, but never enter the MVC reference.
                recorder.set_context(trial=0, block=0, phase='calibration_recovery')
                while True:
                    calibration_keys(display)
                    if grip.error:
                        raise RuntimeError('Grip reader failed; reconnect and restart calibration') from grip.error
                    draw('本次未计入 请松开握力器', f'已完成 {trial-1} / 3 次有效记录\n等待有效数据，恢复后休息并重试',
                         0, phase='recovery')
                    display.win.flip()
                    try:
                        sample = grip.latest(max_age=c['max_gap_s'])
                        # The recovery frame must postdate the failed measurement.
                        if sample.get('t', -math.inf) >= measured['observed_end_s']:
                            break
                    except RuntimeError:
                        pass
                acquire(f'rest_{trial}', c['rest_s'])
        values = reference(result['segments'], config)
        result.update(status='complete', reference=values)
        config['task'].update(grip_min=values['zero_raw'], grip_max=values['reference_max_raw'],
                              lift_gain=values['effective_lift_gain'])
        setup.save()
        recorder.record('event', {'name': 'calibration_complete', 'reference': values})
        recorder.flush()
        display.event.clearEvents()
        while True:
            keys = calibration_keys(display)
            if 'space' in keys:
                break
            peaks = ' / '.join(f'{p:.4f}' for p in values['peaks_raw'])
            fraction = values['equilibrium_fraction']
            balance = f'{fraction:.1%}' if fraction is not None else '不可计算'
            draw('校准完成 请松开握力器',
                f"零点 {values['zero_raw']:.4f}\n三次峰值 {peaks}\n"
                f"参考最大值 {values['reference_max_raw']:.4f}\n"
                f"lift_gain = {values['effective_lift_gain']:.2f}   理论平衡握力 {balance}\n"
                f"参考 lift_gain：20% → {config['task']['gravity']/.2:.1f}；30% → {config['task']['gravity']/.3:.1f}\n"
                '按空格开始实验，Esc 退出', 1,
                phase='complete', peaks=values['peaks_raw'])
            display.win.flip()
    except BaseException as exc:
        if result['status'] != 'complete':
            result['status'] = 'aborted' if isinstance(exc, CalibrationAborted) else 'error'
        result['exit_reason'] = type(exc).__name__ + ': ' + str(exc)
        setup.save()
        raise
