"""UNO R3 grip demo: real serial acquisition, threshold task, and session recording.

Run from any directory. Requires this repository; real hardware requires pyserial.
No PsychoPy window or marker Arduino is needed. --simulate uses synthetic data.
"""
import argparse
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from gripflight.grip import GripReader
from gripflight.ports import resolve_ports
from gripflight.recording import Recorder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'config.json')
    parser.add_argument('--port', help='COM6 or /dev/cu.usbmodem...; overrides USB identity')
    parser.add_argument('--serial-number', help='Override grip USB serial number')
    parser.add_argument('--list-ports', action='store_true')
    parser.add_argument('--simulate', action='store_true', help='Synthetic data, no Arduino')
    parser.add_argument('--seconds', type=float, default=10)
    parser.add_argument('--zero', type=float, default=0.81, help='Example zero voltage; replace after calibration')
    parser.add_argument('--reference', type=float, default=1.20, help='Example reference voltage; replace after calibration')
    parser.add_argument('--threshold', type=float, default=0.20, help='Fraction of zero-to-reference range')
    parser.add_argument('--output', type=Path, default=ROOT / 'data' / 'grip_demo')
    args = parser.parse_args()
    if args.list_ports:
        from serial.tools import list_ports
        for port in sorted(list_ports.comports(), key=lambda p: p.device):
            print(f'{port.device}  serial={port.serial_number}  {port.description}')
        return 0
    if not all(math.isfinite(x) for x in (args.seconds, args.zero, args.reference, args.threshold)):
        parser.error('Parameters must be finite numbers')
    if args.seconds <= 0 or not 0 <= args.zero < args.reference <= 5 or not 0 < args.threshold < 1:
        parser.error('Require seconds>0, 0<=zero<reference<=5, and 0<threshold<1')
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    config['markers']['enabled'] = False
    if args.serial_number:
        config.setdefault('serial_devices', {})['grip'] = args.serial_number
    resolve_ports(config, {'grip': args.port} if args.port else {}, simulate=args.simulate)
    parameters = dict(demo='voltage_threshold', simulated=args.simulate,
                      port=config['grip']['port'], baud=250000, sample_rate=256,
                      zero_v=args.zero, reference_v=args.reference, threshold=args.threshold,
                      seconds=args.seconds)
    recorder = Recorder(args.output, parameters)
    reader = None
    status, code = 'error', 1
    try:
        # The existing reader owns the serial thread, packet parsing and timing checks.
        reader = GripReader(recorder, port=parameters['port'], baud=250000, gain=1.0,
                            require_timing=True, sample_rate=256, ordered=True,
                            simulate=args.simulate).start()
        reader.wait_ready(timeout=5)
        recorder.set_context(phase='demo', trial=1)
        reader.begin_task()
        started = time.perf_counter()
        recorder.record('event', {'name': 'demo_start', 'simulated': args.simulate})
        previous_above = False
        next_print, next_flush = 0.0, 1.0
        latest = None
        while (elapsed := time.perf_counter() - started) < args.seconds:
            if args.simulate:
                fraction = (1 - math.cos(2 * math.pi * elapsed / 4)) / 2
                reader.simulated_voltage = args.zero + fraction * (args.reference - args.zero)
            # Drain all samples; never make one old reading stand for new samples.
            for sample in reader.take_samples():
                if not sample['valid']:
                    recorder.record('task', {'grip_valid': False,
                        'grip_sample_id': sample['record_id'], 'grip_task_used': False})
                    continue
                relative = max(0.0, min(1.0, (sample['voltage'] - args.zero) /
                                       (args.reference - args.zero)))
                above = relative >= args.threshold
                recorder.record('task', {'grip_sample_id': sample['record_id'],
                    'grip_device_sequence': sample['device_sequence'],
                    'grip_acquisition_id': sample['acquisition_id'],
                    'grip_valid': True, 'grip_task_used': True,
                    'task_use_host_s': recorder.now(), 'raw': sample['raw'],
                    'normalized': relative, 'above_threshold': above})
                if above != previous_above:
                    recorder.record('event', {'name': 'threshold_enter' if above else 'threshold_exit',
                        'grip_sample_id': sample['record_id'], 'simulated': args.simulate})
                previous_above = above
                latest = sample, relative
            if elapsed >= next_print and latest:
                sample, relative = latest
                print(f"{elapsed:5.1f}s  V={sample['voltage']:.3f}  "
                      f"relative={relative:6.1%}  seq={sample['device_sequence']}")
                next_print = elapsed + 0.2  # Display 5 Hz; acquisition remains 256 Hz.
            if elapsed >= next_flush:
                recorder.flush()
                next_flush = elapsed + 1.0
            time.sleep(0.005)
        recorder.record('event', {'name': 'demo_end', 'simulated': args.simulate})
        status, code = 'complete', 0
    except KeyboardInterrupt:
        status, code = 'aborted', 130
    except Exception as exc:
        recorder.record('diagnostic', {'error': str(exc)})
        print(f'Demo stopped: {exc}', file=sys.stderr)
    finally:
        try:
            if reader is not None:
                reader.close()
        except Exception as exc:
            status, code = 'error', 1
            recorder.record('diagnostic', {'error': str(exc)})
            print(f'Acquisition error: {exc}', file=sys.stderr)
        finally:
            recorder.close(status)
            print(f'Status: {status}\nData: {recorder.directory}')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
