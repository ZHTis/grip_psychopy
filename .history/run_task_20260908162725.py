"""Run from PsychoPy Coder or: python run_task.py --simulate."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from gripflight.grip import GripReader
from gripflight.markers import MarkerOutput
from gripflight.recording import Recorder
from gripflight.task import Task, load_map, validate_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    parser.add_argument('--simulate', action='store_true', help='No hardware; mouse left/space gives full grip')
    parser.add_argument('--headless', action='store_true', help='Fast logic smoke test, requires --simulate')
    args = parser.parse_args()
    if args.headless and not args.simulate:
        parser.error('--headless requires --simulate')
    config_path = Path(args.config).resolve()
    root = config_path.parent
    config = json.loads(config_path.read_text(encoding='utf-8-sig'))
    validate_config(config)
    if not args.simulate:
        if not config['markers']['port']:
            parser.error('Set markers.port in config.json to the SECOND Arduino COM port')
        if config['markers']['port'].upper() == config['grip']['port'].upper():
            parser.error('Grip and marker ports must be different')
    objects, finish = load_map(root/config['map'])
    task = Task(config['task'], objects, finish)
    config['runtime'] = {'simulate': args.simulate, 'headless': args.headless,
        'source_hashes': {p: hashlib.sha256((root/p).read_bytes()).hexdigest()
                          for p in [config['map'], *config['assets'].values()]},
        'effective_phase_blocks': task.durations, 'dt_s': task.dt}
    recorder = Recorder(root/config['output'], config)
    grip = marker = display = None
    status = 'error'
    try:
        if not args.headless:
            from gripflight.display import Display
            display = Display(config, root, objects)
        grip = GripReader(recorder, simulate=args.simulate,
                          **{k: config['grip'][k] for k in ('port', 'baud', 'gain')}).start()
        grip.wait_ready()
        marker = MarkerOutput(recorder, simulate=args.simulate, **config['markers'])
        next_tick = time.perf_counter()
        last_flush = next_tick
        def emit(name, snapshot):
            recorder.set_context(**{k: snapshot[k] for k in ('trial', 'block', 'phase')})
            marker.send(name, task=snapshot, timing='headless' if args.headless else 'callOnFlip')
            if name == 'trial_end':
                recorder.record('trial', snapshot)
        while True:
            marker.check()
            if display:
                keys = display.event.getKeys()
                if 'escape' in keys:
                    status = 'aborted'
                    marker.send('abort', reason='escape')
                    break
                if args.simulate:
                    grip.simulated_voltage = config['task']['grip_max'] if (
                        display.mouse.getPressed()[0] or 'space' in keys) else config['task']['grip_min']
            now = time.perf_counter()
            if args.headless or now >= next_tick:
                if not args.headless and now-next_tick > max(.5, 2*task.dt):
                    raise RuntimeError('Task stalled; cannot preserve source-block timing')
                sample = grip.latest(config['grip']['stale_timeout_s'])
                task.tick(sample['raw'])
                recorder.set_context(trial=task.trial, block=1, phase=task.phase)
                recorder.record('task', dict(task.snapshot(), grip_sample_id=sample['record_id'],
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
            status = 'error'
            recorder.record('diagnostic', {'cleanup_errors': cleanup_errors})
        recorder.close(status)
        print('Session:', recorder.directory)
        print('Status:', status)
        if cleanup_errors:
            raise RuntimeError('; '.join(cleanup_errors))


if __name__ == '__main__':
    main()
