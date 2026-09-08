"""Independent asynchronous marker output; every request and response is recorded."""
import queue
import threading
import time


def encode_marker(event_id, code, pulse_ms, mode='loopback'):
    if mode not in ('loopback', 'output_only'):
        raise ValueError('mode must be loopback or output_only')
    if type(code) is not int or not 0 <= code <= 255:
        raise ValueError('Marker code must be an integer 0..255')
    if type(pulse_ms) is not int or not 1 <= pulse_ms <= 1000:
        raise ValueError('pulse_ms must be an integer 1..1000')
    command = 'M' if mode == 'loopback' else 'O'
    return f'{command},{event_id},{code},{pulse_ms}\n'.encode('ascii')


class MarkerOutput:
    def __init__(self, recorder, codes, port=None, baud=115200, pulse_ms=10,
                 transport=None, simulate=False, loopback_pin=None, a0_threshold=512, verbose=False,
                 mode='loopback'):
        if mode not in ('loopback', 'output_only'):
            raise ValueError('mode must be loopback or output_only')
        self.mode = mode
        if loopback_pin is not None and (type(loopback_pin) is not int or not 2 <= loopback_pin <= 9):
            raise ValueError('loopback_pin must be null or D2..D9 as integer 2..9')
        if type(a0_threshold) is not int or not 1 <= a0_threshold <= 1023:
            raise ValueError('a0_threshold must be 1..1023 for 10-bit ADC')
        self.loopback_pin, self.a0_threshold, self.verbose = loopback_pin, a0_threshold, verbose
        self.response_feedback = {}
        self.output_pins = list(range(2,10))
        self.feedback_pins = None
        self.mapping_source = 'legacy_fixed_D2_D9'
        for code in codes.values():
            encode_marker(1, code, pulse_ms)
        self.recorder, self.codes, self.pulse_ms = recorder, codes, pulse_ms
        self.simulate, self.error, self.closed = simulate, None, False
        self.queue = queue.Queue(maxsize=256)
        self.serial = transport
        if not simulate and transport is None:
            import serial
            self.serial = serial.Serial(port, baud, timeout=0.05, write_timeout=0.2)
            try:
                deadline = time.perf_counter() + 5
                while time.perf_counter() < deadline:
                    self.serial.write(b'HELLO\n')
                    response = self.serial.readline().strip()
                    if response.startswith(b'PINS,'):
                        self._pin_map(response.decode('ascii'))
                    if response.startswith(b'ERR,PIN_CONFIG'):
                        raise ValueError('Invalid PinMap.h: check duplicate/reserved/conflicting pins')
                    if response == b'READY,1':
                        break
                else:
                    raise TimeoutError('Marker firmware READY,1 handshake missing')
            except BaseException:
                self.serial.close()
                raise
        self.thread = threading.Thread(target=self._run, name='marker-output', daemon=True)
        self.thread.start()

    def _pin_map(self, line):
        fields = line.split(',')
        if len(fields) != 17 or fields[0] != 'PINS':
            raise ValueError('Invalid pin-map response')
        pins = [int(pin) for pin in fields[1:]]
        if len(set(pins)) != 16 or any(pin < 2 for pin in pins):
            raise ValueError('Pin-map contains duplicate or reserved pins')
        self.output_pins, self.feedback_pins = pins[:8], pins[8:]
        self.mapping_source = 'firmware'
        if self.verbose:
            print(f'Pin map bit0..7: output={self.output_pins}, feedback={self.feedback_pins}', flush=True)

    def check(self):
        if self.error:
            raise RuntimeError('Marker output failed; see events.csv') from self.error

    def send(self, name, **details):
        self.check()
        if self.closed:
            raise RuntimeError('Marker output closed')
        code = self.codes[name]
        event_id = self.recorder.record('marker_request', dict(name=name, code=code,
                    pulse_ms=self.pulse_ms, simulated=self.simulate, mode=self.mode,
                    output_pins=self.output_pins, feedback_pins=self.feedback_pins,
                    mapping_source=self.mapping_source, **details))
        try:
            self.queue.put_nowait((event_id, code))
        except queue.Full:
            self.recorder.record('marker_error', {'event_id': event_id, 'error': 'Queue full'})
            raise RuntimeError('Marker queue full')
        return event_id

    def _response(self, expected, event_id, code, deadline):
        self.response_feedback = self._feedback(None, expected, code)
        buffer = bytearray()
        while time.perf_counter() < deadline:
            buffer.extend(self.serial.read(1))
            if len(buffer) > 256:
                raise RuntimeError('Oversize marker response')
            if not buffer.endswith(b'\n'):
                continue
            line = bytes(buffer).decode('ascii').strip()
            buffer.clear()
            if line == 'READY,1':
                continue
            if line.startswith('PINS,'):
                self._pin_map(line)
                continue
            fields = line.split(',')
            if len(fields) not in (4, 5, 6) or fields[:3] != [expected, str(event_id), str(code)]:
                raise RuntimeError('Unexpected marker response: ' + line)
            if len(fields) == 6:
                if fields[4:] == ['OUT', '-']:
                    if self.mode != 'output_only':
                        raise ValueError('Expected loopback feedback, firmware reported output_only')
                    if self.verbose:
                        print(f'RX {line} | output_only: firmware confirmation; no pin readback', flush=True)
                    return int(fields[3])
                if self.mode == 'output_only':
                    raise ValueError('Expected OUT confirmation for output_only mode')
                if fields[4] != 'B8':
                    raise ValueError('Unknown feedback protocol: ' + fields[4])
                readback = int(fields[5])
                if not 0 <= readback <= 255:
                    raise ValueError('Readback code must be 0..255')
                target = code if expected == 'ACK' else 0
                self.response_feedback.update(feedback_mode='eight_bit', readback_code=readback,
                    expected_readback_code=target, readback_bits=f'{readback:08b}',
                    mismatch_mask=readback ^ target, readback_matches_expected=readback == target,
                    mismatched_output_pins=[self.output_pins[bit] for bit in range(8) if (readback ^ target) & (1 << bit)],
                    mismatched_feedback_pins=None if self.feedback_pins is None else
                        [self.feedback_pins[bit] for bit in range(8) if (readback ^ target) & (1 << bit)],
                    output_pins=self.output_pins, feedback_pins=self.feedback_pins, mapping_source=self.mapping_source)
                if self.verbose:
                    print(f'RX {line} | bit7..bit0={readback:08b} expected={target:08b} '
                          f'check={readback == target} mismatch_pins={self.response_feedback["mismatched_output_pins"]}', flush=True)
                return int(fields[3])
            if self.mode == 'output_only':
                raise ValueError('Output-only requires updated firmware with OUT confirmations')
            adc = int(fields[4]) if len(fields) == 5 else None
            if adc is not None and not 0 <= adc <= 1023:
                raise ValueError('A0 ADC value outside 0..1023')
            self.response_feedback = self._feedback(adc, expected, code)
            if self.verbose:
                print(f'RX {line} | A0 check={self.response_feedback["a0_matches_expected"]}', flush=True)
            return int(fields[3])
        raise TimeoutError(f'{expected} timeout for event {event_id}')

    def _feedback(self, adc, phase, code):
        expected_high = None if self.loopback_pin is None else (
            bool(code & (1 << (self.loopback_pin-2))) if phase == 'ACK' else False)
        measured_high = None if adc is None else adc >= self.a0_threshold
        return {'a0_adc': adc, 'loopback_pin': self.loopback_pin,
                'a0_expected_high': expected_high, 'a0_measured_high': measured_high,
                'a0_matches_expected': None if expected_high is None or adc is None else expected_high == measured_high,
                'mode': self.mode,
                'feedback_mode': 'disabled' if self.mode == 'output_only' else ('single_a0' if adc is not None else 'unavailable'),
                'readback_code': None, 'expected_readback_code': code if phase == 'ACK' else 0,
                'readback_bits': None, 'mismatch_mask': None,
                'readback_matches_expected': None, 'mismatched_output_pins': None}

    def _run(self):
        while True:
            item = self.queue.get()
            try:
                if item is None:
                    return
                event_id, code = item
                if self.error:
                    self.recorder.record('marker_error', {'event_id': event_id, 'error': 'Cancelled after previous error'})
                    continue
                sent = self.recorder.now()
                if self.simulate:
                    self.recorder.record('marker_ack', {'event_id': event_id, 'code': code,
                        't_write_host_s': sent, 'device_micros': None, 'simulated': True,
                        **self._feedback(None, 'ACK', code)})
                    time.sleep(self.pulse_ms / 1000)
                    device_done = None
                    done_feedback = self._feedback(None, 'DONE', code)
                else:
                    packet = encode_marker(event_id, code, self.pulse_ms, self.mode)
                    if self.verbose:
                        print('TX ' + packet.decode().strip(), flush=True)
                    if self.serial.write(packet) != len(packet):
                        raise IOError('Incomplete marker write')
                    deadline = time.perf_counter() + 2 + self.pulse_ms / 1000
                    device_start = self._response('ACK', event_id, code, deadline)
                    self.recorder.record('marker_ack', {'event_id': event_id, 'code': code,
                        't_write_host_s': sent, 'device_micros': device_start, 'simulated': False,
                        **self.response_feedback})
                    device_done = self._response('DONE', event_id, code, deadline)
                    done_feedback = dict(self.response_feedback)
                self.recorder.record('marker_done', {'event_id': event_id, 'code': code,
                    'device_micros': device_done, 'simulated': self.simulate, **done_feedback})
            except Exception as exc:
                self.error = exc
                self.recorder.record('marker_error', {'event_id': item[0] if item else None, 'error': repr(exc)})
            finally:
                self.queue.task_done()

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.queue.put(None)
        self.thread.join(max(10, (self.queue.qsize() + 1) * (3 + self.pulse_ms / 1000)))
        if self.thread.is_alive():
            raise RuntimeError('Marker shutdown timed out; recorder must remain open')
        if self.serial:
            self.serial.close()
        self.check()
