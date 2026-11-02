"""Shared session lifecycle and game loop, independent of the selected sensor."""
import copy
import hashlib
import json
import time

from .calibration import CalibrationAborted, ExperimentSetup
from .calibration_profile import configure_mode, prepare_calibration
from .input_devices import device_class
from .markers import MarkerOutput
from .paths import PROJECT_ROOT, project_path
from .runtime import ContinuingDevices, ContinuingRecorder
from .task import Task, load_map, validate_config


def advance_task(task, control, recorder):
    """One physics slot; preserve invalid slots and original acquisition links."""
    used_at = recorder.now()
    before = task.phase
    task.c['lift_gain'] = control.lift_gain
    task.tick(control.normalized, valid=control.valid, raw=control.raw)
    recorder.set_context(trial=task.trial, block=1, phase=task.phase)
    recorder.record('task', dict(task.snapshot(), **control.record_fields(used_at),
        input_normalized=control.normalized, grip_task_used=before=='feedback' and control.valid,
        applied_lift=control.lift_gain*task.smoothed))


def game_loop(task, device, display, devices, recorder, config, headless):
    """Device supplies ordered control slots; game rules and events are shared."""
    last_flush = time.perf_counter()
    def emit(name, snapshot):
        recorder.set_context(**{k:snapshot[k] for k in ('trial', 'block', 'phase')})
        devices.send(name, config['markers']['codes'][name], task=snapshot,
                     timing='headless' if headless else 'callOnFlip')
        if name == 'trial_end':
            recorder.record('trial', snapshot)
    while True:
        keys = display.event.getKeys() if display else []
        if device.stop_requested or 'escape' in keys:
            devices.send('abort', config['markers']['codes']['abort'], reason='user_stop')
            return 'aborted'
        devices.check_marker()
        now = time.perf_counter()
        pressed = bool(display and display.mouse.getPressed()[0])
        for control in device.read_inputs(now, keys, pressed):
            advance_task(task, control, recorder)
            if task.phase == 'complete':
                break
        events = task.take_events()
        device.present(task, display)
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
            return 'complete'


def run(args, device_name=None):
    root = PROJECT_ROOT
    cls = device_class(device_name or args.grip_device)
    config = json.loads(project_path(args.config or cls.default_config).read_text(encoding='utf-8-sig'))
    original = copy.deepcopy(config)
    if args.markers_enabled is not None:
        config['markers']['enabled'] = args.markers_enabled
    if args.marker_mode is not None:
        config['markers']['mode'] = args.marker_mode
    if args.fullscreen:
        config['display']['fullscreen'] = True
    if args.windowed:
        config['display'].update(fullscreen=False, screen=0)
    configure_mode(config, args)
    device = cls(config, args, root)
    device.configure()
    validate_config(config)
    objects, finish = load_map(root/config['map'])
    task = Task(config['task'], objects, finish)
    sources = [config['map'], *config['assets'].values(), *device.extra_sources,
               'gripflight/runner.py', 'gripflight/runtime.py', 'gripflight/event_log.py', 'gripflight/gl_safety.py', 'gripflight/display.py', 'gripflight/calibration_profile.py', 'gripflight/task.py', 'gripflight/input_devices/base.py']
    config['runtime'] = dict(device.runtime, simulate=args.simulate, headless=args.headless,
        grip_device=device.name, input_contract='normalized_effort_v1',
        debug_mode=config['calibration']['debug_mode'],
        effective_phase_blocks=task.durations, dt_s=task.dt,
        source_hashes={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in sources})
    recorder = ContinuingRecorder(root/config['output'], config)
    devices = ContinuingDevices(recorder, config['task'].get('grip_min', 0),
                                markers_enabled=config['markers'].get('enabled', True))
    display = marker = setup = None
    status = 'error'
    try:
        setup = ExperimentSetup(recorder, original, config, (root/config['map']).read_bytes(), objects)
        if not args.headless:
            display = device.create_display(objects)
        device.start(recorder, devices, display)
        if devices.markers_enabled:
            try:
                if not args.simulate and (not config['markers']['port'] or
                        config['markers']['port'].casefold() == (device.port or '').casefold()):
                    raise ValueError('Marker port missing or same as grip port')
                marker = MarkerOutput(recorder, simulate=args.simulate,
                    **{k:v for k,v in config['markers'].items() if k != 'enabled'})
                devices.marker = marker
            except Exception as exc:
                if device.strict_markers:
                    raise
                devices.warning('marker_start', exc)
        else:
            print('Hardware markers disabled; local event recording remains active.')
        prepare_calibration(device, display, setup)
        validate_config(config)
        task = Task(config['task'], objects, finish)
        device.begin_task()
        setup.data['grip_acquisition_id'] = device.acquisition_id
        setup.data['status'] = 'task_running'
        device.save_setup(setup)
        recorder.set_context(trial=0, block=1, phase='pre_run')
        if recorder.backend:
            recorder.backend._metadata()
        status = game_loop(task, device, display, devices, recorder, config, args.headless)
        if display and status == 'complete' and device.completion_hold_s:
            deadline = time.perf_counter()+device.completion_hold_s
            while time.perf_counter() < deadline:
                if device.stop_requested or 'escape' in display.event.getKeys():
                    break
                display.draw(task)
                display.win.flip()
    except (CalibrationAborted, KeyboardInterrupt):
        status = 'aborted'
        devices.send('abort', config['markers']['codes']['abort'], reason='user_stop')
    except BaseException as exc:
        recorder.record('diagnostic', dict(category='runtime', error=repr(exc), continued=False))
        devices.send('abort', config['markers']['codes']['abort'], reason=str(exc))
        raise
    finally:
        # Close controls first (join pending edits), then markers while sampling
        # is still active, then the reader and display. Archive final parameters.
        cleanup = []
        actions = [device.stop_controls]
        if marker:
            actions.append(marker.close)
        actions.append(device.close)
        if display:
            actions.append(display.close)
        for close in actions:
            try:
                close()
            except Exception as exc:
                cleanup.append(repr(exc))
        if cleanup:
            status = 'error'
            recorder.warn('cleanup', '; '.join(cleanup))
            recorder.record('diagnostic', dict(cleanup_errors=cleanup))
        if device.strict_recording and recorder.dropped_records:
            status = 'error'
        if setup:
            setup.data.update(status=status, runtime_warnings=dict(recorder.warnings),
                              dropped_records=recorder.dropped_records)
            try:
                device.save_setup(setup)
            except Exception as exc:
                status = 'error'
                recorder.warn('setup_save', exc)
        recorder.close(status)
        print('Session:', recorder.directory)
        print('Status:', status)
