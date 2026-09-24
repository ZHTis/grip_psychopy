"""Run from PsychoPy Coder or: python run_task.py --simulate."""
import argparse
import copy
import hashlib
import json
import time
from pathlib import Path

from gripflight.grip import GripReader
from gripflight.markers import MarkerOutput
from gripflight.runtime import ContinuingRecorder, ContinuingDevices
from gripflight.task import Task, load_map, validate_config
from gripflight.paths import PROJECT_ROOT, project_path
from gripflight.ports import resolve_ports
from gripflight.calibration import ExperimentSetup, run_calibration, CalibrationAborted, settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json', help='Path relative to project root')
    parser.add_argument('--grip-port', help='Override grip port, e.g. COM6 or /dev/cu.usbmodem1301')
    parser.add_argument('--marker-port', help='Override marker port, e.g. COM10 or /dev/cu.usbmodem1401')
    parser.add_argument('--list-ports', action='store_true', help='List serial ports and exit without starting a session')
    parser.add_argument('--simulate', action='store_true', help='No hardware; mouse left/space gives full grip')
    marker_switch = parser.add_mutually_exclusive_group()
    marker_switch.add_argument('--no-markers', dest='markers_enabled', action='store_false', help='Real grip input, local events only; no marker board needed')
    marker_switch.add_argument('--enable-markers', dest='markers_enabled', action='store_true', help='Enable hardware marker output')
    parser.set_defaults(markers_enabled=None)
    parser.add_argument('--headless', action='store_true', help='Fast logic smoke test, requires --simulate')
    parser.add_argument('--marker-mode', choices=['loopback', 'output_only'], help='Override markers.mode for this run')
    args = parser.parse_args()
    if args.list_ports:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda port: port.device)
        for port in ports:
            print(f'{port.device}\n  {port.description}\n  {port.hwid}')
        if not ports:
            print('No serial ports found.')
        return
    if args.headless and not args.simulate:
        parser.error('--headless requires --simulate')
    config_path = project_path(args.config)
    root = PROJECT_ROOT
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    original_config = copy.deepcopy(config)
    settings(config)
    if args.markers_enabled is not None:
        config['markers']['enabled'] = args.markers_enabled
    overrides = {}
    for section, override in (('grip', args.grip_port), ('markers', args.marker_port)):
        if override is not None:
            if not override.strip():
                parser.error(f'{section} port must not be empty')
            overrides[section] = override.strip()
    try:
        resolve_ports(config, overrides, simulate=args.simulate)
    except ValueError as exc:
        parser.error(str(exc))
    if args.marker_mode is not None:
        config['markers']['mode'] = args.marker_mode
    validate_config(config)
    if config['task']['sample_block_size'] != 1 or config['task']['sampling_rate'] != config['grip'].get('sample_rate', 256):
        parser.error('Ordered acquisition requires sample_block_size=1 and task sampling_rate=grip sample_rate')
    objects, finish = load_map(root/config['map'])
    task = Task(config['task'], objects, finish)
    config['runtime'] = {'simulate': args.simulate, 'headless': args.headless,
        'source_hashes': {p: hashlib.sha256((root/p).read_bytes()).hexdigest()
                          for p in [config['map'], *config['assets'].values()]},
        'effective_phase_blocks': task.durations, 'dt_s': task.dt}
    recorder = ContinuingRecorder(root/config['output'], config)
    devices = ContinuingDevices(recorder, config['task']['grip_min'],
                                markers_enabled=config['markers'].get('enabled', True))
    grip = marker = display = None
    status = 'error'
    setup = None
    try:
        setup = ExperimentSetup(recorder, original_config, config, (root/config['map']).read_bytes(), objects)
        if not args.headless:
            from gripflight.display import Display
            display = Display(config, root, objects)
        try:
            grip = GripReader(recorder, simulate=args.simulate,
                              ordered=True, **{k: v for k, v in config['grip'].items() if k != 'stale_timeout_s'}).start()
            devices.grip = grip
        except Exception as exc:
            devices.warning('grip_start', exc)
        if devices.markers_enabled:
            try:
                if not args.simulate and (not config['markers']['port'] or
                        config['markers']['port'].upper() == config['grip']['port'].upper()):
                    raise ValueError('Marker port missing or same as grip port')
                marker = MarkerOutput(recorder, simulate=args.simulate, **{k: v for k, v in config['markers'].items() if k != 'enabled'})
                devices.marker = marker
            except Exception as exc:
                devices.warning('marker_start', exc)
        else:
            print('Hardware markers disabled; real grip input and local event recording remain active.')
        run_calibration(display, grip, recorder, config, setup)
        validate_config(config)
        devices.fallback_raw = config['task']['grip_min']
        # Recreate the task after calibration; run_start belongs to the task, not calibration.
        task = Task(config['task'], objects, finish)
        if not args.headless:
            if grip is None:
                raise RuntimeError('Grip reader unavailable')
            grip.wait_ready()
            grip.begin_task()
        setup.data['grip_acquisition_id'] = grip.acquisition_id if grip else None
        setup.data['status'] = 'task_running'
        setup.save()
        recorder.set_context(trial=0, block=1, phase='pre_run')
        if recorder.backend:
            recorder.backend._metadata()
        next_tick = time.perf_counter()
        last_flush = next_tick
        def emit(name, snapshot):
            recorder.set_context(**{k: snapshot[k] for k in ('trial', 'block', 'phase')})
            devices.send(name, config['markers']['codes'][name], task=snapshot,
                         timing='headless' if args.headless else 'callOnFlip')
            if name == 'trial_end':
                recorder.record('trial', snapshot)
        while True:
            try:
                devices.check_marker()
                if display:
                    keys = display.event.getKeys()
                    if 'escape' in keys:
                        status = 'aborted'
                        devices.send('abort', config['markers']['codes']['abort'], reason='escape')
                        break
                    if args.simulate and grip:
                        grip.simulated_voltage = (config['task']['grip_max'] if (
                            display.mouse.getPressed()[0] or 'space' in keys) else config['task']['grip_min']) / abs(config['grip']['gain'])
                now = time.perf_counter()
                samples = ([dict(raw=config['task']['grip_min'], valid=True, record_id=None,
                                 device_sequence=None, acquisition_id=None, t=None)]
                           if args.headless else grip.take_samples())
                for sample in samples:
                    used_at = recorder.now()
                    physics_used = task.phase == 'feedback' and sample['valid']
                    task.tick(sample['raw'], valid=sample['valid'])
                    recorder.set_context(trial=task.trial, block=1, phase=task.phase)
                    recorder.record('task', dict(task.snapshot(), grip_sample_id=sample['record_id'],
                        grip_valid=sample['valid'], grip_device_sequence=sample.get('device_sequence'),
                        grip_acquisition_id=sample.get('acquisition_id'), task_use_host_s=used_at,
                        grip_task_used=physics_used,
                        grip_age_s=used_at-sample['t'] if sample['t'] is not None else None))
                    if task.phase == 'complete':
                        break
                events = task.take_events()
                if display:
                    display.draw(task)
                    for name, snapshot in events:
                        display.win.callOnFlip(emit, name, snapshot)
                    display.win.flip()
                else:
                    for name, snapshot in events:
                        emit(name, snapshot)
                recorder.set_context(trial=task.trial, block=1, phase=task.phase)
                if now-last_flush >= .25:
                    recorder.flush()
                    last_flush = now
                if task.phase == 'complete':
                    status = 'complete'
                    break
            except Exception as exc:
                recorder.record('diagnostic', {'category': 'runtime', 'error': str(exc), 'continued': False})
                raise
        if display and status == 'complete':
            deadline = time.perf_counter() + 1
            while time.perf_counter() < deadline:
                if 'escape' in display.event.getKeys():
                    break
                display.draw(task)
                display.win.flip()
    except CalibrationAborted:
        status = 'aborted'
        devices.send('abort', config['markers']['codes']['abort'], reason='escape_during_calibration')
    except BaseException as exc:
        recorder.record('diagnostic', {'error': repr(exc)})
        if marker:
            try:
                marker.send('abort', reason=repr(exc))
            except Exception as marker_error:
                recorder.record('diagnostic', {'abort_marker_error': repr(marker_error)})
        raise
    finally:
        cleanup_errors = []
        # Keep grip acquisition active while pending markers finish.
        for resource in (marker, grip, display):
            if resource:
                try:
                    resource.close()
                except Exception as exc:
                    cleanup_errors.append(repr(exc))
        if cleanup_errors:
            recorder.warn('cleanup', '; '.join(cleanup_errors))
            recorder.record('diagnostic', {'cleanup_errors': cleanup_errors})
        if setup is not None:
            setup.data['status'] = status
            setup.data['runtime_warnings'] = dict(recorder.warnings)
            setup.data['dropped_records'] = recorder.dropped_records
            try:
                setup.save()
            except Exception as exc:
                recorder.warn('setup_save', exc)
        recorder.close(status)
        print('Session:', recorder.directory)
        print('Status:', status)


if __name__ == '__main__':
    main()
