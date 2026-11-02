import csv
import json
import struct
import tempfile
import time
import unittest

from gripflight.multichannel import RXG0505MParser, MultiChannelGripReader
from gripflight.recording import Recorder, export_existing

# Manufacturer manual, page 20. The last byte is the published checksum.
MANUAL_FRAME = bytes.fromhex('40 31 00 13 11 00 11 01 00 20 08 00 1A 00 00 15 1F 00 '
    '00 66 00 23 11 00 12 00 00 50 1F 01 01 28 00 08 15 00 13 01 01 23 02 11 '
    '00 30 10 01 01 18 00 38 10 22 8E')
MANUAL_VALUES = [19,4352,4353,32,2048,6656,21,7936,102,35,4352,4608,80,
                 7937,296,8,5376,4865,291,529,48,4097,280,56,4130]


def packet(hand=0x32, values=None):
    if values is None:
        values = [0, 65535, 0x4031, 0x4032, 0x0a0d] + list(range(20))
    body = bytes([0x40, hand]) + struct.pack('>25H', *values)
    return body + bytes([sum(body) & 0xff])


class FakeSerial:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.closed = False
        self.writes = []
    @property
    def in_waiting(self):
        return 4096
    def read(self, n):
        if self.chunks:
            chunk = self.chunks.pop(0)
            if isinstance(chunk, Exception):
                raise chunk
            return chunk
        time.sleep(.001)
        return b''
    def write(self, data):
        self.writes.append(data)
        raise AssertionError('The passive receiver must never be sent a command')
    def close(self):
        self.closed = True


class ParserTests(unittest.TestCase):
    def test_manufacturer_frame_all_25_channels(self):
        self.assertEqual(len(MANUAL_FRAME), 53)
        sample, = RXG0505MParser().feed(MANUAL_FRAME)
        self.assertEqual(sample['values_g'], MANUAL_VALUES)
        self.assertEqual(sample['hand'], 'left')
        self.assertEqual(sample['hand_code'], 1)
        self.assertEqual(sample['frame_hex'], MANUAL_FRAME.hex())

    def test_every_split_and_bytewise(self):
        for split in range(54):
            with self.subTest(split=split):
                p = RXG0505MParser()
                samples = p.feed(MANUAL_FRAME[:split])+p.feed(MANUAL_FRAME[split:])
                self.assertEqual([s['values_g'] for s in samples], [MANUAL_VALUES])
                self.assertEqual(p.buffer, b'')
        p = RXG0505MParser()
        frames = []
        for value in MANUAL_FRAME:
            frames.extend(p.feed(bytes([value])))
        self.assertEqual(len(frames), 1)

    def test_batched_hands_binary_payload_and_range(self):
        p = RXG0505MParser()
        frames = p.feed(MANUAL_FRAME + packet() + MANUAL_FRAME)
        self.assertEqual([s['hand'] for s in frames], ['left', 'right', 'left'])
        self.assertEqual(frames[1]['values_g'][:5], [0,65535,0x4031,0x4032,0x0a0d])
        self.assertEqual(p.checksum_errors, 0)

    def test_noise_bad_checksum_and_recovery(self):
        bad = bytearray(MANUAL_FRAME)
        bad[-1] ^= 1
        p = RXG0505MParser()
        frames = p.feed(b'noise\x40\x33' + bad + packet())
        self.assertEqual([s['hand'] for s in frames], ['right'])
        self.assertEqual(p.checksum_errors, 1)
        self.assertEqual(p.discarded_bytes, 7+53)

    def test_dropped_byte_recovers_following_frame(self):
        p = RXG0505MParser()
        frames = p.feed(MANUAL_FRAME[:15]+MANUAL_FRAME[16:]+packet())
        self.assertEqual([s['hand'] for s in frames], ['right'])
        self.assertGreaterEqual(p.checksum_errors, 1)

    def test_short_false_header_does_not_discard_valid_header(self):
        p = RXG0505MParser()
        self.assertEqual(p.feed(b'\x40'), [])
        frames = p.feed(MANUAL_FRAME)
        self.assertEqual(len(frames), 1)
        self.assertEqual(p.discarded_bytes, 1)

    def test_noise_memory_and_type(self):
        p = RXG0505MParser()
        self.assertEqual(p.feed(b'x'*100000), [])
        self.assertEqual(len(p.buffer), 0)
        with self.assertRaises(TypeError):
            p.feed('40 31')


class ReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.r = Recorder(self.tmp.name, {'device': 'RX-G0505M'})
        self.g = None
    def tearDown(self):
        if self.g:
            try:
                self.g.close()
            except RuntimeError:
                pass
        self.r.close()
        self.tmp.cleanup()
    def wait_for(self, predicate):
        until = time.perf_counter()+2
        while not predicate() and time.perf_counter()<until:
            time.sleep(.002)
        self.assertTrue(predicate())
    def rows(self, kind):
        with self.r.lock:
            return [json.loads(row[0]) for row in self.r.db.execute(
                'SELECT payload FROM records WHERE kind=? ORDER BY id', (kind,))]

    def test_thread_records_all_frames_wide_csv_and_raw_replay(self):
        stream = b'junk'+MANUAL_FRAME+packet()+MANUAL_FRAME[:11]
        serial = FakeSerial([stream[:6], stream[6:40], stream[40:]])
        self.g = MultiChannelGripReader(self.r, transport=serial, ordered=True).start()
        self.g.wait_ready(hand='both')
        self.assertEqual(self.g.latest('left')['values_g'], MANUAL_VALUES)
        self.assertFalse(self.g.latest('left')['device_timed'])
        self.assertIsNone(self.g.latest('left')['device_sequence'])
        queued = self.g.take_samples()
        self.assertEqual([s['hand'] for s in queued], ['left', 'right'])
        self.assertEqual(self.g.take_samples(), [])
        queued[0]['values_g'][0] = 99999
        self.assertEqual(self.g.latest('left')['values_g'][0], 19)
        self.g.close()
        self.assertTrue(serial.closed)
        self.assertEqual(serial.writes, [])
        self.assertEqual(self.g.stats()['pending_bytes'], 11)
        raw = b''.join(bytes.fromhex(row['chunk_hex']) for row in self.rows('grip_multichannel_bytes'))
        self.assertEqual(raw, stream)
        self.assertEqual(len(RXG0505MParser().feed(raw)), 2)
        self.assertIn('incomplete_frame', [r['category'] for r in self.rows('diagnostic')])
        directory = self.r.directory
        self.r.close()
        export_existing(directory)
        with (directory/'grip_multichannel.csv').open(encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(len(rows), 2)
        self.assertEqual([int(rows[0][f'point_{i:02d}_g']) for i in range(1,26)], MANUAL_VALUES)
        self.assertEqual(rows[0]['device_sequence'], '')
        self.assertEqual(rows[0]['simulated'], 'False')
        self.assertEqual(rows[1]['hand'], 'right')
        self.assertEqual(rows[0]['t_host_s'], rows[1]['t_host_s'])  # Same final read chunk.

    def test_missing_and_stale_per_hand(self):
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([MANUAL_FRAME])).start()
        self.g.wait_ready(hand='left')
        with self.assertRaises(TimeoutError):
            self.g.wait_ready(timeout=.02, hand='both')
        with self.assertRaises(RuntimeError):
            self.g.latest('right')
        time.sleep(.01)
        with self.assertRaisesRegex(RuntimeError, 'stale'):
            self.g.latest('left', max_age=.001)
        with self.assertRaises(ValueError):
            self.g.latest('left', max_age=float('nan'))

    def test_no_data_startup_timeout_and_clean_close(self):
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([])).start()
        with self.assertRaises(TimeoutError):
            self.g.wait_ready(timeout=.02)
        self.g.close()
        self.g.close()

    def test_disconnection_surfaces_error_and_keeps_recording(self):
        serial = FakeSerial([MANUAL_FRAME, OSError('receiver disconnected')])
        self.g = MultiChannelGripReader(self.r, transport=serial).start()
        self.wait_for(lambda: self.g.error is not None)
        with self.assertRaisesRegex(RuntimeError, 'disconnected'):
            self.g.check()
        with self.assertRaises(RuntimeError):
            self.g.close()
        self.assertTrue(serial.closed)
        self.assertEqual(len(self.rows('grip_multichannel')), 1)

    def test_queue_overflow_reports_error_after_saving_whole_chunk(self):
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([MANUAL_FRAME*3]),
                                       ordered=True, queue_capacity=1).start()
        self.wait_for(lambda: self.g.error is not None)
        with self.assertRaisesRegex(RuntimeError, 'overflow'):
            self.g.take_samples()
        self.assertEqual(len(self.rows('grip_multichannel')), 3)
        self.assertEqual(self.g.stats()['queued_frames'], 1)

    def test_latest_only_does_not_accumulate_queue(self):
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([MANUAL_FRAME*20]), queue_capacity=1).start()
        self.wait_for(lambda: self.g.stats()['valid_frames'] == 20)
        self.g.check()
        self.assertEqual(self.g.stats()['queued_frames'], 0)
        with self.assertRaisesRegex(RuntimeError, 'ordered=True'):
            self.g.take_samples()
        with self.assertRaises(RuntimeError):
            self.g.start()

    def test_corrupt_frame_is_not_published(self):
        bad = MANUAL_FRAME[:-1]+b'\x00'
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([bad+MANUAL_FRAME])).start()
        self.g.wait_ready()
        self.g.close()
        self.assertEqual(self.g.stats()['valid_frames'], 1)
        self.assertEqual(self.g.stats()['checksum_errors'], 1)
        self.assertEqual(self.rows('diagnostic')[0]['category'], 'resync')

    def test_simulation_marks_every_sample_and_both_hands(self):
        self.g = MultiChannelGripReader(self.r, simulate=True).start()
        self.g.wait_ready(hand='both')
        self.g.close()
        rows = self.rows('grip_multichannel')
        self.assertEqual({r['hand'] for r in rows}, {'left','right'})
        self.assertTrue(all(r['simulated'] and len(r['values_g'])==25 for r in rows))
        self.assertTrue(all(r['device_micros'] is None for r in rows))

    def test_recording_failure_is_visible(self):
        def failed_record(*args):
            raise OSError('disk unavailable')
        self.r.record = failed_record
        self.g = MultiChannelGripReader(self.r, transport=FakeSerial([MANUAL_FRAME])).start()
        self.wait_for(lambda: self.g.error is not None)
        with self.assertRaisesRegex(RuntimeError, 'disk unavailable'):
            self.g.check()
        # Allow tearDown to finalize diagnostics after the simulated storage fault.
        del self.r.record


if __name__ == '__main__':
    unittest.main()
