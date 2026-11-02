"""Record every RX-G0505M channel, with terminal preview and no game mapping."""
import argparse
import math
import sys
import time

from gripflight.multichannel import MultiChannelGripReader, BAUD, CHANNEL_COUNT
from gripflight.paths import project_path
from gripflight.recording import Recorder


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    selection = p.add_mutually_exclusive_group()
    selection.add_argument('--port', help='Receiver port, e.g. COM6 or /dev/cu.usbserial-130')
    selection.add_argument('--serial-number', help='Unique USB receiver serial number, if available')
    p.add_argument('--list-ports', action='store_true')
    p.add_argument('--simulate', action='store_true', help='Generated test frames; no hardware')
    p.add_argument('--hand', choices=['any', 'left', 'right', 'both'], default='any',
                   help='Hands required for readiness/freshness. All received hands are always saved.')
    p.add_argument('--seconds', type=float, default=0, help='Duration after first required data; 0 until Ctrl+C')
    p.add_argument('--timeout', type=float, default=5, help='Startup wait in seconds')
    p.add_argument('--stale-seconds', type=float, default=2, help='Stop if required hand(s) have no new data')
    p.add_argument('--output', default='data/multichannel', help='Output root, relative to project unless absolute')
    args = p.parse_args(argv)
    if args.list_ports:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda item: item.device)
        for item in ports:
            print(f'{item.device}\n  {item.description}\n  serial={item.serial_number}  {item.hwid}')
        if not ports:
            print('No serial ports found.')
        return 0
    if not all(math.isfinite(x) for x in (args.seconds, args.timeout, args.stale_seconds)) or args.seconds < 0 or args.timeout <= 0 or args.stale_seconds <= 0:
        p.error('seconds must be >=0; timeout and stale-seconds must be >0; all must be finite')
    if args.simulate and (args.port or args.serial_number):
        p.error('--simulate cannot be combined with a hardware port/serial number')
    if not args.simulate:
        if args.serial_number:
            from serial.tools import list_ports
            matches = [item.device for item in list_ports.comports() if item.serial_number == args.serial_number]
            if len(matches) != 1:
                p.error(f'Expected exactly one receiver with serial {args.serial_number}, found {len(matches)}')
            args.port = matches[0]
        if not args.port:
            p.error('Use --list-ports and specify --port, or use --simulate')
    parameters = dict(device='RX-G0505M', port=args.port, baud=BAUD, channel_count=CHANNEL_COUNT,
        channel_order=list(range(1, 26)), units='g (device-reported; no extra calibration)',
        simulated=args.simulate, required_hand=args.hand, seconds=args.seconds,
        stale_seconds=args.stale_seconds, device_timestamps=False, device_sequence=False,
        timestamp_meaning='host receipt of serial chunk containing frame end; not sampling time',
        simulation_rate_per_hand_hz=20 if args.simulate else None, game_mapping=None)
    recorder = Recorder(project_path(args.output), parameters)
    recorder.set_context(phase='multichannel_acquisition')
    reader = None
    status, exit_code = 'error', 1
    print('Session:', recorder.directory)
    print('SIMULATED DATA' if args.simulate else 'RX-G0505M: 115200 / 8N1; receiving all channels; no device commands sent')
    try:
        hands = ('left', 'right') if args.hand in ('any', 'both') else (args.hand,)
        reader = MultiChannelGripReader(recorder, port=args.port, simulate=args.simulate,
                                        simulated_hands=hands).start()
        # Use latest() for preview. Every frame is recorded by the background thread.
        reader.wait_ready(timeout=args.timeout, hand=None if args.hand == 'any' else args.hand)
        recorder.record('event', {'name': 'multichannel_ready', 'simulated': args.simulate})
        start = time.perf_counter()
        next_print = next_flush = start
        while args.seconds == 0 or time.perf_counter()-start < args.seconds:
            reader.check()
            fresh, stale = {}, {}
            for hand in ('left', 'right'):
                try:
                    fresh[hand] = reader.latest(hand, max_age=args.stale_seconds)
                except RuntimeError as exc:
                    stale[hand] = str(exc)
            required = ('left', 'right') if args.hand == 'both' else (args.hand,)
            if args.hand == 'any':
                if not fresh:
                    raise RuntimeError('No fresh RX-G0505M frames from either hand')
            else:
                for hand in required:
                    if hand not in fresh:
                        raise RuntimeError(stale[hand])
            now = time.perf_counter()
            if now >= next_print:
                for hand in ('left', 'right'):
                    if hand in fresh:
                        sample = fresh[hand]
                        values = ' '.join(f'{i:02d}:{v}' for i, v in enumerate(sample['values_g'], 1))
                        print(f'{hand:5} [device g] {values}', flush=True)
                    else:
                        print(f'{hand:5} -- no fresh data', flush=True)
                stats = reader.stats()
                print(f"frames={stats['valid_frames']} checksum_errors={stats['checksum_errors']} "
                      f"discarded_bytes={stats['discarded_bytes']}", flush=True)
                next_print = now+1
            if now >= next_flush:
                recorder.flush()
                next_flush = now+.25
            time.sleep(.01)
        recorder.record('event', {'name': 'multichannel_end', 'simulated': args.simulate})
        status, exit_code = 'complete', 0
    except KeyboardInterrupt:
        status, exit_code = 'aborted', 130
        recorder.record('event', {'name': 'multichannel_abort', 'simulated': args.simulate})
    except Exception as exc:
        recorder.record('diagnostic', {'source': 'multichannel_cli', 'error': str(exc)})
        print(f'Acquisition stopped: {exc}', file=sys.stderr)
    finally:
        try:
            if reader is not None:
                reader.close()
        except Exception as exc:
            status, exit_code = 'error', 1
            print(f'Close error: {exc}', file=sys.stderr)
        finally:
            recorder.close(status)
            print(f'Status: {status}\nSaved: {recorder.directory}')
    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
