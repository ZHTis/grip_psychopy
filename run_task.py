"""Run from PsychoPy Coder or: python run_task.py --simulate."""
import argparse
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default='config.json', help='Path relative to project root')
    parser.add_argument('--grip-port', help='Override grip port, e.g. COM6 or /dev/cu.usbmodem1301')
    parser.add_argument('--marker-port', help='Override marker port, e.g. COM10 or /dev/cu.usbmodem1401')
    parser.add_argument('--list-ports', action='store_true', help='List serial ports and exit without starting a session')
    parser.add_argument('--simulate', action='store_true', help='No hardware; mouse left/space gives full grip')
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
    objects, finish = load_map(root/config['map'])
    task = Task(config['task'], objects, finish)
    config['runtime'] = {'simulate': args.simulate, 'headless': args.headless,
        'source_hashes': {p: hashlib.sha256((root/p).read_bytes()).hexdigest()
                          for p in [config['map'], *config['assets'].values()]},
        'effective_phase_blocks': task.durations, 'dt_s': task.dt}
    recorder = ContinuingRecorder(root/config['output'], config)
    devices = ContinuingDevices(recorder, config['task']['grip_min'])
    grip = marker = display = None
    status = 'error'
    try:
        if not args.headless:
            from gripflight.display import Display
            display = Display(config, root, objects)
        try:
            grip = GripReader(recorder, simulate=args.simulate,
                              **{k: config['grip'][k] for k in ('port', 'baud', 'gain')}).start()
            devices.grip = grip
        except Exception as exc:
            devices.warning('grip_start', exc)
        try:
            if not args.simulate and (not config['markers']['port'] or
                    config['markers']['port'].upper() == config['grip']['port'].upper()):
                raise ValueError('Marker port missing or same as grip port')
            marker = MarkerOutput(recorder, simulate=args.simulate, **config['markers'])
            devices.marker = marker
        except Exception as exc:
            devices.warning('marker_start', exc)
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
                        grip.simulated_voltage = config['task']['grip_max'] if (
                            display.mouse.getPressed()[0] or 'space' in keys) else config['task']['grip_min']
                now = time.perf_counter()
                if args.headless or now >= next_tick:
                    if not args.headless and now-next_tick > max(.5, 2*task.dt):
                        devices.warning('timing', f'Task update late by {now-next_tick:.3f}s; resuming without catch-up')
                        next_tick = now
                    sample = devices.sample(config['grip']['stale_timeout_s'])
                    task.tick(sample['raw'])
                    recorder.set_context(trial=task.trial, block=1, phase=task.phase)
                    recorder.record('task', dict(task.snapshot(), grip_sample_id=sample['record_id'],
                                                grip_input_status=sample['input_status'], grip_age_s=sample['age_s'],
                                                scheduled_lateness_s=0 if args.headless else now-next_tick))
                    next_tick += task.dt
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
                devices.warning('runtime', exc)
                next_tick = time.perf_counter() + task.dt
                time.sleep(.01)
        if display and status == 'complete':
            deadline = time.perf_counter() + 1
            while time.perf_counter() < deadline:
                if 'escape' in display.event.getKeys():
                    break
                display.draw(task)
                display.win.flip()
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
        recorder.close(status)
        print('Session:', recorder.directory)
        print('Status:', status)


if __name__ == '__main__':
    main()
