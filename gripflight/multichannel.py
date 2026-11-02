"""RX-G0505M binary acquisition, independent of game mapping and PsychoPy.

One frame carries one hand's 25 values in manufacturer-reported g units.
There is no device sequence or timestamp. Times below are host receipt times.
"""
from collections import deque
import math
import struct
import threading
import time
import uuid

CHANNEL_COUNT = 25
FRAME_SIZE = 53
BAUD = 115200
HANDS = {0x31: 'left', 0x32: 'right'}


class RXG0505MParser:
    """Incremental parser; use a single instance per serial stream."""
    def __init__(self):
        self.buffer = bytearray()
        self.valid_frames = 0
        self.checksum_errors = 0
        self.discarded_bytes = 0

    def feed(self, chunk):
        if not isinstance(chunk, (bytes, bytearray)):
            raise TypeError('Expected raw serial bytes, not decoded text')
        self.buffer.extend(chunk)
        frames = []
        while self.buffer:
            start = self.buffer.find(b'\x40')
            if start < 0:
                self.discarded_bytes += len(self.buffer)
                self.buffer.clear()
                break
            if start:
                self.discarded_bytes += start
                del self.buffer[:start]
            if len(self.buffer) < 2:
                break
            if self.buffer[1] not in HANDS:
                del self.buffer[0]
                self.discarded_bytes += 1
                continue
            if len(self.buffer) < FRAME_SIZE:
                break
            packet = bytes(self.buffer[:FRAME_SIZE])
            if sum(packet[:52]) & 0xff != packet[52]:
                self.checksum_errors += 1
                self.discarded_bytes += 1
                del self.buffer[0]  # Search again; do not discard a whole frame.
                continue
            frames.append(dict(hand=HANDS[packet[1]], hand_code=packet[1]-0x30,
                               values_g=list(struct.unpack('>25H', packet[2:52])),
                               frame_hex=packet.hex()))
            self.valid_frames += 1
            del self.buffer[:FRAME_SIZE]
        return frames


def _positive(value, name):
    if not math.isfinite(value) or value <= 0:
        raise ValueError(name + ' must be finite and positive')


def _copy(sample):
    return dict(sample, values_g=list(sample['values_g']))


class MultiChannelGripReader:
    """Background serial reader; records all frames before publishing samples.

    start()/wait_ready()/latest(hand) work independently of screen refresh.
    ordered=True additionally enables take_samples(), a bounded task queue.
    Call close() BEFORE closing the shared Recorder. Never sends commands.
    """
    def __init__(self, recorder, port=None, *, transport=None, ordered=False,
                 queue_capacity=4096, simulate=False, simulated_hands=('left', 'right'),
                 simulation_rate=20.0):
        if type(queue_capacity) is not int or queue_capacity < 1:
            raise ValueError('queue_capacity must be a positive integer')
        _positive(simulation_rate, 'simulation_rate')
        simulated_hands = tuple(simulated_hands)
        if not simulated_hands or len(set(simulated_hands)) != len(simulated_hands) or any(h not in HANDS.values() for h in simulated_hands):
            raise ValueError('simulated_hands must contain distinct left/right entries')
        if simulate and transport is not None:
            raise ValueError('Simulation cannot use a real transport')
        self.recorder = recorder
        self.acquisition_id = uuid.uuid4().hex
        self.simulate = simulate
        self.simulated_values_g = None  # Optional 25-value override for game simulation.
        self.ordered, self.queue_capacity = ordered, queue_capacity
        self.simulated_hands, self.simulation_rate = simulated_hands, simulation_rate
        self.parser = RXG0505MParser()
        self.lock = threading.RLock()
        self.queue = deque()
        self.latest_samples = {}
        self.bytes_received = 0
        self.received_index = 0
        self.counts = dict(left=0, right=0)
        self.error = None
        self.stop_event = threading.Event()
        self.started = self.closed = False
        self.serial = transport
        if not simulate and transport is None:
            if not port:
                raise ValueError('Provide the RX-G0505M receiver serial port')
            import serial
            self.serial = serial.Serial(port=port, baudrate=BAUD, bytesize=8,
                parity='N', stopbits=1, timeout=0.05, write_timeout=0.1,
                xonxoff=False, rtscts=False, dsrdtr=False)
        self.thread = threading.Thread(target=self._run, name='grip-25ch', daemon=True)

    def _record(self, kind, payload, t=None):
        record_id = self.recorder.record(kind, payload, t)
        if record_id is None:
            raise RuntimeError('Multichannel recording failed; no record ID returned')
        return record_id

    def start(self):
        if self.started or self.closed:
            raise RuntimeError('Reader instances can only be started once')
        self.started = True
        self.thread.start()
        return self

    def _accept(self, chunk, received_at, host_unix_s):
        # Only the acquisition thread calls this method. Keep the original bytes
        # so corrupt packets and the final partial packet can be inspected later.
        self._record('grip_multichannel_bytes', dict(acquisition_id=self.acquisition_id,
            chunk_hex=chunk.hex(), byte_count=len(chunk), host_unix_s=host_unix_s,
            simulated=self.simulate), received_at)
        with self.lock:
            self.bytes_received += len(chunk)
            before = (self.parser.checksum_errors, self.parser.discarded_bytes)
            frames = self.parser.feed(chunk)
            after = (self.parser.checksum_errors, self.parser.discarded_bytes)
        if after != before:
            self._record('diagnostic', dict(source='grip_multichannel',
                acquisition_id=self.acquisition_id, category='resync',
                checksum_errors_added=after[0]-before[0],
                discarded_bytes_added=after[1]-before[1],
                error='Discarded corrupt or unaligned input; searching for next valid frame'), received_at)
        overflow = False
        for frame in frames:
            self.received_index += 1
            sample = dict(frame, acquisition_id=self.acquisition_id,
                received_index=self.received_index, t=received_at,
                host_unix_s=host_unix_s, simulated=self.simulate,
                valid=True, device_timed=False, device_sequence=None, device_micros=None)
            sample['record_id'] = self._record('grip_multichannel', sample, received_at)
            with self.lock:
                self.latest_samples[sample['hand']] = sample
                self.counts[sample['hand']] += 1
                if self.ordered:
                    if len(self.queue) >= self.queue_capacity:
                        overflow = True
                    else:
                        self.queue.append(sample)
        if overflow:
            raise RuntimeError('Multichannel task queue overflow; frames saved, consumer must drain more often')

    def _run(self):
        try:
            sim_step = 0
            while not self.stop_event.is_set():
                if self.simulate:
                    chunk = bytearray()
                    for offset, hand in enumerate(self.simulated_hands):
                        override = self.simulated_values_g
                        values = list(override) if override is not None else [
                            round(1000*(1+math.sin(sim_step*.10+i*.24+offset))) for i in range(CHANNEL_COUNT)]
                        if len(values) != CHANNEL_COUNT or any(type(v) is not int or not 0 <= v <= 65535 for v in values):
                            raise ValueError('Simulation override requires 25 uint16 integers')
                        body = bytes((0x40, 0x31 if hand == 'left' else 0x32)) + struct.pack('>25H', *values)
                        chunk.extend(body + bytes((sum(body) & 0xff,)))
                    sim_step += 1
                else:
                    chunk = self.serial.read(max(1, min(self.serial.in_waiting, 4096)))
                received_at, host_unix_s = self.recorder.now(), time.time()
                if chunk:
                    self._accept(bytes(chunk), received_at, host_unix_s)
                if self.simulate:
                    # Demo pacing only. No synthetic device timestamp is exposed.
                    self.stop_event.wait(1/self.simulation_rate)
        except Exception as exc:
            with self.lock:
                self.error = exc
            try:
                self._record('diagnostic', dict(source='grip_multichannel',
                    acquisition_id=self.acquisition_id, category='reader_error', error=str(exc)))
            except Exception:
                pass  # Keep the original recording or transport failure available.

    def check(self):
        with self.lock:
            if self.error:
                raise RuntimeError('RX-G0505M acquisition failed: '+str(self.error)) from self.error

    def stats(self):
        with self.lock:
            return dict(bytes_received=self.bytes_received, valid_frames=sum(self.counts.values()),
                frames_by_hand=dict(self.counts), checksum_errors=self.parser.checksum_errors,
                discarded_bytes=self.parser.discarded_bytes, pending_bytes=len(self.parser.buffer),
                queued_frames=len(self.queue), simulated=self.simulate)

    def latest(self, hand, max_age=2.0):
        if hand not in HANDS.values():
            raise ValueError('hand must be left or right')
        _positive(max_age, 'max_age')
        self.check()
        with self.lock:
            sample = self.latest_samples.get(hand)
            if sample is None:
                raise RuntimeError('No RX-G0505M data for '+hand)
            sample = _copy(sample)
        if self.recorder.now()-sample['t'] > max_age:
            raise RuntimeError('RX-G0505M '+hand+' data is stale')
        return sample

    def wait_ready(self, timeout=5.0, hand=None):
        _positive(timeout, 'timeout')
        if hand not in (None, 'left', 'right', 'both'):
            raise ValueError('hand must be None, left, right or both')
        deadline = time.perf_counter()+timeout
        while time.perf_counter() < deadline:
            self.check()
            with self.lock:
                recent = {h for h, s in self.latest_samples.items()
                          if self.recorder.now()-s['t'] <= 2.0}
            if (hand is None and recent) or (hand == 'both' and len(recent) == 2) or hand in recent:
                return
            if self.closed:
                raise RuntimeError('Reader is closed')
            time.sleep(.005)
        raise TimeoutError('No valid RX-G0505M data for '+str(hand or 'either hand')+'; check receiver, BL light and serial port')

    def take_samples(self):
        if not self.ordered:
            raise RuntimeError('Construct reader with ordered=True to use take_samples')
        self.check()
        with self.lock:
            samples = [_copy(s) for s in self.queue]
            self.queue.clear()
        return samples

    def close(self):
        if self.closed:
            self.check()
            return
        self.stop_event.set()
        if self.started:
            self.thread.join(2)
        if self.thread.is_alive():
            raise RuntimeError('Reader has not stopped; do not close its recorder yet')
        try:
            if self.serial is not None:
                self.serial.close()
        finally:
            self.closed = True
        if self.parser.buffer:
            self._record('diagnostic', dict(source='grip_multichannel',
                acquisition_id=self.acquisition_id, category='incomplete_frame',
                pending_hex=self.parser.buffer.hex(),
                error='Partial frame retained in raw byte records at shutdown'))
        self._record('grip_multichannel_summary', dict(acquisition_id=self.acquisition_id, **self.stats()))
        self.check()
