import json
import tempfile
import time
import unittest
from gripflight.markers import MarkerOutput, encode_marker
from gripflight.recording import Recorder


class FakeMarkerSerial:
    def __init__(self, wrong=False): self.buffer, self.writes, self.wrong = bytearray(), [], wrong
    def write(self, packet):
        self.writes.append(packet)
        _, event_id, code, width = packet.decode().strip().split(',')
        if self.wrong: code = '999'
        self.buffer.extend(f'ACK,{event_id},{code},100\nDONE,{event_id},{code},10100\n'.encode())
        return len(packet)
    def read(self, n):
        value = bytes(self.buffer[:n]); del self.buffer[:n]
        return value
    def close(self): pass


class MarkerTests(unittest.TestCase):
    def test_timeout_does_not_fabricate_ack(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {})
            m = MarkerOutput(r, {'a': 1}, transport=FakeMarkerSerial())
            with self.assertRaises(TimeoutError): m._response('ACK', 1, 1, time.perf_counter()-1)
            self.assertEqual(r.db.execute("SELECT count(*) FROM records WHERE kind='marker_ack'").fetchone()[0], 0)
            m.close(); r.close()

    def test_all_256_codes(self):
        for code in range(256):
            self.assertEqual(encode_marker(12, code, 10), f'M,12,{code},10\n'.encode())
            self.assertEqual(sum(((code >> b) & 1) << b for b in range(8)), code)
        for code in (-1, 256, 1.5, True):
            with self.assertRaises(ValueError): encode_marker(1, code, 10)

    def test_order_repeated_codes_and_replies(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {})
            s = FakeMarkerSerial()
            m = MarkerOutput(r, {'a': 128}, transport=s)
            ids = [m.send('a') for _ in range(3)]
            m.close()
            self.assertEqual(s.writes, [encode_marker(i, 128, 10) for i in ids])
            acks = [json.loads(row[0]) for row in r.db.execute("SELECT payload FROM records WHERE kind='marker_ack'")]
            self.assertEqual([a['event_id'] for a in acks], ids)
            self.assertTrue(all(a['device_micros'] == 100 for a in acks))
            r.close()

    def test_bad_ack_is_failure(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {})
            m = MarkerOutput(r, {'a': 1}, transport=FakeMarkerSerial(wrong=True))
            m.send('a')
            with self.assertRaises(RuntimeError): m.close()
            self.assertEqual(r.db.execute("SELECT count(*) FROM records WHERE kind='marker_error'").fetchone()[0], 1)
            r.close('error')


if __name__ == '__main__': unittest.main()
