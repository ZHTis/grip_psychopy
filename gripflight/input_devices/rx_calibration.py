"""RX per-point calibration and pressure-map calibration pages."""
import statistics

from ..calibration import CalibrationAborted, settings
from ..weights import evaluate


def save_setup(setup, model, **extra):
    setup.data['weighted_input'] = dict(model.snapshot(), **extra)
    setup.save()


def calibrate(display, reader, model, state, recorder, config, setup):
    c = settings(config)
    source_hand = config['multichannel']['hand']
    result = setup.data['calibration']
    result.update(kind='multichannel_per_point', units='device-reported g', segments=[])
    if config['runtime']['headless'] or not c['enabled']:
        result['status'] = 'skipped_headless' if config['runtime']['headless'] else 'disabled'
        result['note'] = 'Uncalibrated test reference: zero=0 and reference range=1000 g per point'
        print('25 通道直接试玩：已跳过零点和最大握力标定；临时参考每点 1000 g，可在面板调节参考倍率。', flush=True)
        save_setup(setup, model)
        return
    model.locked = True
    result['status'] = 'running'
    schedule = [('zero', c['zero_s']), ('squeeze_1', c['squeeze_s']),
                ('rest_1', c['rest_s']), ('squeeze_2', c['squeeze_s']),
                ('rest_2', c['rest_s']), ('squeeze_3', c['squeeze_s'])]
    try:
        for phase, duration in schedule:
            rest = phase.startswith('rest')
            title = '正在准备 请勿触碰' if phase == 'zero' else ('请松开握力器 休息' if rest else '最大力度握紧')
            if reader.simulate:
                reader.simulated_values_g = [1000 if phase.startswith('squeeze') else 0]*25
            reader.take_samples()  # Exclude previously queued frames from this phase.
            recorder.set_context(trial=0, block=0, phase='calibration_'+phase)
            segment = dict(phase=phase, samples=[])
            if not rest:
                result['segments'].append(segment)
            def begin():
                segment['start_s'] = recorder.now()
                segment['end_s'] = segment['start_s']+duration
                recorder.record('event', dict(name='calibration_'+phase+'_start', timing='callOnFlip'))
            display.draw_calibration(title, '右手 25 通道'+(' · 模拟自动施力' if reader.simulate else ''), 0)
            display.win.callOnFlip(begin)
            display.win.flip()
            last_save = recorder.now()
            while recorder.now() < segment['end_s']:
                if state.stop or 'escape' in display.event.getKeys():
                    raise CalibrationAborted()
                reader.check()
                latest = reader.latest(source_hand, max_age=c['max_gap_s'])
                display.set_pressure(latest['values_g'])
                batch = reader.take_samples()
                if not rest:
                    segment['samples'].extend(s for s in batch if s['hand']==source_hand and segment['start_s'] <= s['t'] < segment['end_s'])
                remaining = max(0, segment['end_s']-recorder.now())
                state.publish(stage='calibration', message=f'{title} · {remaining:.1f} 秒',
                              values_g=latest['values_g'], fresh=True)
                display.draw_calibration(title, f'右手 · 剩余 {remaining:.1f} 秒', 1-remaining/duration)
                display.win.flip()
                if recorder.now()-last_save > .25:
                    recorder.flush(); setup.save(); last_save = recorder.now()
            batch = reader.take_samples()
            if not rest:
                segment['samples'].extend(s for s in batch if s['hand']==source_hand and segment['start_s'] <= s['t'] < segment['end_s'])
                times = [s['t'] for s in segment['samples']]
                boundaries = [segment['start_s'], *times, segment['end_s']]
                if len(times) < c['min_samples'] or max(b-a for a,b in zip(boundaries, boundaries[1:])) > c['max_gap_s']:
                    raise ValueError(f'校准样本不足或存在过长间断，请检查设备 {source_hand} 数据连接')
            recorder.record('event', dict(name='calibration_'+phase+'_end'))
            setup.save()
        zero, *squeezes = result['segments']
        baseline = [statistics.median(s['values_g'][i] for s in zero['samples']) for i in range(25)]
        peaks = [[max(s['values_g'][i] for s in seg['samples']) for i in range(25)] for seg in squeezes]
        weights = model.snapshot()['weights']
        weight_sum = sum(weights)
        zero_weighted = [sum(w*max(0, v-b) for w,v,b in zip(weights, s['values_g'], baseline))/weight_sum
                         for s in zero['samples']]
        threshold = max(c['min_range'], 5*statistics.pstdev(zero_weighted))
        squeeze_peaks = [max(sum(w*max(0, v-b) for w,v,b in zip(weights, s['values_g'], baseline))/weight_sum
                              for s in seg['samples']) for seg in squeezes]
        if any(peak <= threshold for peak in squeeze_peaks):
            raise ValueError('三次握紧均须超过零点噪声和最小范围，请重新校准')
        ranges = [max(0, max(p[i] for p in peaks)-baseline[i]) for i in range(25)]
        if max(ranges) < c['min_range']:
            raise ValueError('握紧数据没有超过零点，请重新检查接触位置')
        model.calibrate(baseline, ranges)
        result.update(status='complete', baseline_g=baseline, three_peaks_g=peaks,
                      weighted_squeeze_peaks_g=squeeze_peaks, minimum_weighted_range_g=threshold,
                      reference_ranges_g=ranges, reference_rule='per-channel maximum across three squeeze windows minus channel baseline')
        recorder.record('event', dict(name='calibration_complete', baseline_g=baseline, reference_ranges_g=ranges))
        save_setup(setup, model)
        display.event.clearEvents()
        while True:
            if reader.simulate:
                reader.simulated_values_g = [0]*25
            reader.take_samples()
            sample = reader.latest(source_hand, max_age=config['multichannel']['stale_timeout_s'])
            display.set_pressure(sample['values_g'])
            state.publish(stage='calibration_complete', message='校准完成 · 回到游戏窗口按空格开始',
                          values_g=sample['values_g'], fresh=True, result=evaluate(sample['values_g'], model.snapshot()))
            keys = display.event.getKeys()
            if state.stop or 'escape' in keys:
                raise CalibrationAborted()
            if 'space' in keys:
                break
            display.draw_calibration('校准完成 请松开', '按空格开始游戏；权重面板将在游戏开始后解锁', 1)
            display.win.flip()
            if recorder.now()-last_save > .25:
                recorder.flush(); last_save = recorder.now()
    except BaseException as exc:
        result['status'] = 'aborted' if isinstance(exc, CalibrationAborted) else 'error'
        result['exit_reason'] = str(exc)
        setup.save()
        raise
    finally:
        model.locked = False
