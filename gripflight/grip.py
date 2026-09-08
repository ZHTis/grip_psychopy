"""Independent serial acquisition. Stores every line, including malformed lines."""
import math
import threading
import time


def parse_line(line, gain=1.0):
    fields = line.strip().split(',')
    if len(fields) != 2:
        raise ValueError('Expected temperature,voltage')
    temperature, voltage = map(float, fields)
    if not all(math.isfinite(x) for x in (temperature, voltage, gain, voltage * gain)):
        raise ValueError('Non-finite sample')
    return {'temperature': temperature, 'voltage': voltage, 'raw': voltage * gain}


class GripReader:
    def __init__(self, recorder, port=None, baud=115200, gain=1.0, transport=None, simulate=False):
        self.recorder, self.gain, self.simulate = recorder, gain, simulate
        self.lock = threading.Lock()
        self.latest_sample = None
        self.error = None
        self.stop_event = threading.Event()
        self.simulated_voltage = 0.81
        self.serial = transport
        if not simulate and transport is None:
            import serial
            self.serial = serial.Serial(port, baud, timeout=0.05, write_timeout=0.1)
        self.thread = threading.Thread(target=self._run, name='grip-reader', daemon=True)

    def start(self):
        self.thread.start()
        return self

    def accept(self, line):
        t = self.recorder.now()
        try:
            text = line.decode('ascii').strip()
            sample = parse_line(text, self.gain)
        except (UnicodeDecodeError, ValueError) as exc:
            self.recorder.record('grip_invalid', {'line_hex': line.hex(), 'error': str(exc)}, t)
            return
        sample.update(line=text, t=t)
        sample['record_id'] = self.recorder.record('grip', sample, t)
        with self.lock:
            self.latest_sample = sample

    def latest(self, max_age=1.0):
        if self.error:
            raise RuntimeError('Grip acquisition failed') from self.error
        with self.lock:
            sample = self.latest_sample
        if sample is None or self.recorder.now() - sample['t'] > max_age:
            raise RuntimeError('No fresh grip sample; check Arduino/port')
        return dict(sample)

    def wait_ready(self, timeout=5):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            if self.error:
                raise RuntimeError('Grip acquisition failed') from self.error
            with self.lock:
                if self.latest_sample is not None:
                    return
            time.sleep(0.01)
        raise TimeoutError('No valid temperature,voltage received')

    def _run(self):
        buffer = bytearray()
        discarding = False
        try:
            while not self.stop_event.is_set():
                if self.simulate:
                    self.accept(f'25,{self.simulated_voltage}\n'.encode())
                    self.stop_event.wait(0.01)
                    continue
                chunk = self.serial.read(max(1, min(self.serial.in_waiting, 4096)))
                for byte in chunk:
                    if byte == 10:
                        if not discarding:
                            self.accept(bytes(buffer))
                        buffer.clear()
                        discarding = False
                    elif not discarding:
                        buffer.append(byte)
                        if len(buffer) > 4096:
                            self.recorder.record('grip_invalid', {'error': 'Line exceeds 4096 bytes'})
                            buffer.clear()
                            discarding = True
            if buffer:
                self.recorder.record('grip_invalid', {'error': 'Incomplete line at shutdown', 'line_hex': buffer.hex()})
        except Exception as exc:
            self.error = exc

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(2)
        if self.serial:
            self.serial.close()
        if self.thread.is_alive():
            raise RuntimeError('Grip reader did not stop')
        if self.error:
            raise RuntimeError('Grip acquisition failed') from self.error
