"""Independent bench tests, no PsychoPy window required."""
import argparse
import time
from pathlib import Path
from gripflight.grip import GripReader
from gripflight.markers import MarkerOutput
from gripflight.recording import Recorder, export_existing


def main():
    p = argparse.ArgumentParser()
    p.add_argument('module', choices=['grip', 'markers', 'recording', 'export'])
    p.add_argument('--port')
    p.add_argument('--baud', type=int, default=115200)
    p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--codes', default='1,2,4,8,16,32,64,128,255,1,1')
    p.add_argument('--pulse-ms', type=int, default=10)
    p.add_argument('--loopback-pin', type=int, choices=range(2,10), default=None, help='Legacy single-A0 mode only; eight-bit feedback needs no argument')
    p.add_argument('--a0-threshold', type=int, default=512)
    p.add_argument('--simulate', action='store_true')
    p.add_argument('--directory', help='Existing session directory for export')
    p.add_argument('--mode', choices=['loopback','output_only'], default='output_only')
    args = p.parse_args()
    if args.module == 'export':
        if not args.directory: p.error('--directory is required')
        export_existing(args.directory)
        return
    if args.module != 'recording' and not args.simulate and not args.port:
        p.error('--port is required for hardware tests')
    r = Recorder(Path(__file__).parent/'test_data', vars(args))
    resource = None
    status = 'error'
    try:
        if args.module == 'grip':
            resource = GripReader(r, port=args.port, baud=args.baud, simulate=args.simulate).start()
            resource.wait_ready()
            until = time.perf_counter()+args.seconds
            while time.perf_counter() < until:
                print(resource.latest())
                r.flush()
                time.sleep(.25)
        elif args.module == 'markers':
            codes = [int(c.strip()) for c in args.codes.split(',')]
            resource = MarkerOutput(r, {str(i): c for i,c in enumerate(codes)},
                                    port=args.port, baud=args.baud, pulse_ms=args.pulse_ms, simulate=args.simulate,
                                    loopback_pin=args.loopback_pin, a0_threshold=args.a0_threshold, verbose=True, mode=args.mode)
            for i, code in enumerate(codes):
                event_id = resource.send(str(i))
                print(f'Event {event_id}: code={code}, bit7..bit0={code:08b}')
                time.sleep(max(.5, args.pulse_ms/1000+.1))
                resource.check(); r.flush()
        else:
            r.set_context(trial=1, block=1, phase='test')
            event_id = r.record('marker_request', {'name': 'test', 'code': 128, 'simulated': True})
            for i in range(1000): r.record('grip', {'voltage': i/1000, 'raw': i/1000})
            r.record('task', {'saved_parameter': 45})
            r.flush()
            assert r.db.execute("SELECT count(*) FROM records WHERE kind='grip' AND last_marker_id=?", (event_id,)).fetchone()[0] == 1000
            print('PASS: 1000 samples saved with matching marker ID and parameters')
        status = 'complete'
    finally:
        try:
            if resource: resource.close()
        except BaseException:
            status = 'error'
            raise
        finally:
            r.close(status)
            print('Saved:', r.directory)


if __name__ == '__main__': main()
