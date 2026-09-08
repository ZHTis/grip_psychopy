import sqlite3
import tempfile
import time
import unittest
from gripflight.grip import GripReader, parse_line
from gripflight.recording import Recorder


class FakeSerial:
    def __init__(self, chunks): self.chunks, self.closed = list(chunks), False
    @property
    def in_waiting(self): return 1
    def read(self, n):
        if self.chunks: return self.chunks.pop(0)
        time.sleep(.001)
        return b''
    def close(self): self.closed = True


class GripTests(unittest.TestCase):
    def test_parser(self):
        self.assertEqual(parse_line(' 25.2,0.90\r\n', 2)['raw'], 1.8)
        for line in ('boot', '25,nan', '25,inf', '1,2,3', '1,', '1,2abc'):
            with self.subTest(line=line), self.assertRaises(ValueError): parse_line(line)

    def test_fragments_bursts_and_invalid_lines(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {})
            serial = FakeSerial([b'25,0.', b'81\r\n25,0.92\nboot\n', b'25,1.1\n'])
            g = GripReader(r, transport=serial).start()
            g.wait_ready()
            deadline = time.perf_counter()+1
            while g.latest()['voltage'] != 1.1 and time.perf_counter() < deadline: time.sleep(.001)
            self.assertEqual(g.latest()['voltage'], 1.1)
            g.close()
            self.assertTrue(serial.closed)
            self.assertEqual(r.db.execute("SELECT count(*) FROM records WHERE kind='grip'").fetchone()[0], 3)
            self.assertEqual(r.db.execute("SELECT count(*) FROM records WHERE kind='grip_invalid'").fetchone()[0], 1)
            time.sleep(.002)
            with self.assertRaises(RuntimeError): g.latest(max_age=.001)
            r.close()

    def test_no_data_fails(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {})
            g = GripReader(r, transport=FakeSerial([])).start()
            with self.assertRaises(TimeoutError): g.wait_ready(.02)
            g.close(); r.close()


if __name__ == '__main__': unittest.main()
