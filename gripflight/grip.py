"""Independent serial acquisition. Stores every line, including malformed lines."""
import math
import uuid
from collections import deque
import threading
import time


def parse_line(line, gain=1.0, require_timing=False):
    fields = line.strip().split(',')
    if len(fields) not in (2, 4) or (require_timing and len(fields) != 4):
        raise ValueError('Expected temperature,voltage,sequence,device_micros; upload timed firmware (250000 baud)')
    temperature, voltage = map(float, fields[:2])
    if not all(math.isfinite(x) for x in (temperature, voltage, gain, voltage * gain)):
        raise ValueError('Non-finite sample')
    sample = {'temperature': temperature, 'voltage': voltage, 'raw': voltage * gain,
              'valid': True, 'device_timed': len(fields) == 4}
    if len(fields) == 4:
        sample.update(device_sequence=uint32(fields[2]), device_micros=uint32(fields[3]))
    return sample

def uint32(value):
    if not value or not value.isascii() or not value.isdecimal() or int(value) > 0xffffffff:
        raise ValueError('Invalid uint32 sequence/timestamp')
    return int(value)


class GripReader:
    def __init__(self, recorder, port=None, baud=115200, gain=1.0, transport=None, simulate=False,
                 require_timing=False, sample_rate=256, max_missing=10,
                 ordered=False, max_lag_s=.25, startup_delay_s=2.0):
        self.recorder, self.gain, self.simulate = recorder, gain, simulate
        if not math.isfinite(sample_rate) or sample_rate <= 0 or not math.isfinite(max_lag_s) or max_lag_s <= 0 or type(max_missing) is not int or max_missing < 0:
            raise ValueError('Invalid grip sample_rate/max_lag_s/max_missing')
        self.require_timing, self.sample_rate = require_timing, sample_rate
        self.max_missing, self.ordered, self.max_lag_s = max_missing, ordered, max_lag_s
        self.acquisition_id = uuid.uuid4().hex
        self.queue = deque()
        self.previous = None
        self.task_active = False
        self.pending_sync = {}
        self.sync_id = 0
        self.next_sync = 0
        self.startup_delay_s = startup_delay_s if transport is None and not simulate else 0
        self.rate_start = None
        self.rate_count = 0
        self.lock = threading.Lock()
        self.latest_sample = None
        self.capture_samples = None
        self.capture_overflow = False
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

    def accept(self, line, received_at=None):
        t = self.recorder.now() if received_at is None else received_at
        try:
            text = line.decode('ascii').strip()
            if text.startswith('S,'):
                fields = text.split(',')
                if len(fields) != 4:
                    raise ValueError('Malformed clock reply')
                token, t2, t3 = map(uint32, fields[1:])
                t1 = self.pending_sync.pop(token, None)
                if t1 is None:
                    raise ValueError('Unmatched clock reply')
                self.recorder.record('grip_sync', dict(acquisition_id=self.acquisition_id,
                    sync_id=token, host_t1_s=t1, host_t4_s=t,
                    device_t2_us=t2, device_t3_us=t3), t)
                return
            sample = parse_line(text, self.gain, self.require_timing)
        except (UnicodeDecodeError, ValueError) as exc:
            self.recorder.record('grip_invalid', {'line_hex': line.hex(), 'error': str(exc)}, t)
            if self.require_timing:
                raise RuntimeError(str(exc)) from exc
            return
        sample.update(line=text, t=t, acquisition_id=self.acquisition_id, simulated=self.simulate)
        try:
            self.validate_timing(sample)
        except RuntimeError as exc:
            self.recorder.record('grip_invalid', {'line': text, 'error': str(exc)}, t)
            raise
        self.store_sample(sample)

    def validate_timing(self, sample):
        if sample['device_timed']:
            seq, us = sample['device_sequence'], sample['device_micros']
            if self.previous is not None:
                old_seq, old_us = self.previous
                delta = (seq-old_seq) & 0xffffffff
                interval = (us-old_us) & 0xffffffff
                if not 1 <= delta <= self.max_missing+1:
                    raise RuntimeError('Grip sequence duplicate/reset/long gap')
                expected = 1e6/self.sample_rate*delta
                if not .8*expected <= interval <= 1.2*expected:
                    raise RuntimeError('Grip device interval does not match configured sample rate')
                for i in range(1, delta):
                    self.store_sample(dict(valid=False, device_timed=False,
                        device_sequence=(old_seq+i)&0xffffffff, device_micros=None,
                        voltage=None, raw=None, temperature=None, t=None,
                        acquisition_id=self.acquisition_id, simulated=self.simulate))
            self.previous = (seq, us)
        elif self.previous is not None:
            raise RuntimeError('Timed stream changed to legacy format')
        if self.require_timing and not self.simulate:
            if self.rate_start is None:
                self.rate_start = sample['t']
                self.rate_count = 0
            self.rate_count += 1
            elapsed = sample['t']-self.rate_start
            if elapsed >= 3:
                rate = (self.rate_count-1)/elapsed
                if abs(rate/self.sample_rate-1) > .1:
                    raise RuntimeError('Grip host arrival rate differs by more than 10%')
                self.rate_start = sample['t']
                self.rate_count = 1

    def store_sample(self, sample):
        sample['record_id'] = self.recorder.record('grip', sample, sample['t'])
        with self.lock:
            if sample['valid']:
                self.latest_sample = sample
                if self.capture_samples is not None:
                    if len(self.capture_samples) >= 100000:
                        self.capture_overflow = True
                    else:
                        self.capture_samples.append(dict(sample))
            if self.ordered and self.task_active:
                if len(self.queue) >= 4096:
                    raise RuntimeError('Grip task queue overflow')
                self.queue.append(dict(sample))

    def begin_task(self):
        with self.lock:
            self.queue.clear()
            self.task_active = True

    def take_samples(self):
        if self.error:
            raise RuntimeError('Grip acquisition failed: '+str(self.error)) from self.error
        with self.lock:
            samples = list(self.queue)
            self.queue.clear()
            latest = self.latest_sample
        now = self.recorder.now()
        valid = [s for s in samples if s['valid']]
        if valid and now-valid[0]['t'] > self.max_lag_s:
            raise RuntimeError('Grip task backlog exceeds max_lag_s')
        if latest is None or now-latest['t'] > 1:
            raise RuntimeError('No fresh grip data; task stopped')
        return samples

    def service_sync(self):
        now = self.recorder.now()
        self.pending_sync = {k:v for k,v in self.pending_sync.items() if now-v < 2}
        if not self.require_timing or now < self.next_sync:
            return
        self.sync_id = self.sync_id % 0xffffffff + 1
        packet = f'Q,{self.sync_id}\n'.encode('ascii')
        self.pending_sync[self.sync_id] = self.recorder.now()
        if self.serial.write(packet) != len(packet):
            raise IOError('Incomplete grip clock request write')
        self.next_sync = now+.5

    def start_capture(self):
        with self.lock:
            self.capture_samples = []
            self.capture_overflow = False

    def drain_capture(self):
        with self.lock:
            if self.capture_overflow:
                raise RuntimeError('Calibration sample buffer overflow')
            samples = self.capture_samples or []
            if self.capture_samples is not None:
                self.capture_samples = []
            return samples

    def stop_capture(self):
        with self.lock:
            samples = self.capture_samples or []
            self.capture_samples = None
            if self.capture_overflow:
                raise RuntimeError('Calibration sample buffer overflow')
            return samples

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
        raise TimeoutError('No valid grip data; check firmware, baud and port')

    def _run(self):
        buffer = bytearray()
        discarding = False
        try:
            if self.startup_delay_s:
                if self.stop_event.wait(self.startup_delay_s):
                    return
                self.serial.reset_input_buffer()
                # Opening a live stream may cut a frame. Discard through one newline.
                discarding = True
            sim_seq = 0
            sim_deadline = time.perf_counter()
            while not self.stop_event.is_set():
                if self.simulate:
                    us = round(sim_seq*1e6/self.sample_rate) & 0xffffffff
                    self.accept(f'25,{self.simulated_voltage},{sim_seq & 0xffffffff},{us}\n'.encode())
                    sim_seq += 1
                    sim_deadline += 1/self.sample_rate
                    self.stop_event.wait(max(0, sim_deadline-time.perf_counter()))
                    continue
                chunk = self.serial.read(max(1, min(self.serial.in_waiting, 4096)))
                received_at = self.recorder.now()
                for byte in chunk:
                    if byte == 10:
                        if not discarding:
                            self.accept(bytes(buffer), received_at)
                        buffer.clear()
                        discarding = False
                    elif not discarding:
                        buffer.append(byte)
                        if len(buffer) > 4096:
                            self.recorder.record('grip_invalid', {'error': 'Line exceeds 4096 bytes'})
                            buffer.clear()
                            discarding = True
                            if self.require_timing:
                                raise RuntimeError('Oversize grip frame')
                self.service_sync()
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
