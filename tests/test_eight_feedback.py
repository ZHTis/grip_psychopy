import json
import tempfile
import unittest
from gripflight.markers import MarkerOutput
from gripflight.recording import Recorder


class EightSerial:
    def __init__(self, corrupt_bit=None, after=0):
        self.corrupt_bit, self.after, self.buffer = corrupt_bit, after, bytearray()
    def write(self, packet):
        _, eid, code, width = packet.decode().strip().split(',')
        readback = int(code) if self.corrupt_bit is None else int(code) ^ (1 << self.corrupt_bit)
        self.buffer.extend(f'ACK,{eid},{code},100,B8,{readback}\nDONE,{eid},{code},10100,B8,{self.after}\n'.encode())
        return len(packet)
    def read(self, n):
        result=bytes(self.buffer[:n]); del self.buffer[:n]; return result
    def close(self): pass


class EightFeedbackTests(unittest.TestCase):
    def test_all_256_codes_readback_and_return_to_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Recorder(folder,{})
            m=MarkerOutput(r,{str(i):i for i in range(256)},transport=EightSerial())
            for code in range(256): m.send(str(code))
            m.close()
            rows=[json.loads(row[0]) for row in r.db.execute("SELECT payload FROM records WHERE kind='marker_ack' ORDER BY id")]
            self.assertEqual([row['readback_code'] for row in rows],list(range(256)))
            self.assertTrue(all(row['readback_matches_expected'] for row in rows))
            done=[json.loads(row[0]) for row in r.db.execute("SELECT payload FROM records WHERE kind='marker_done'")]
            self.assertEqual(len(done),256)
            self.assertTrue(all(row['readback_code']==0 and row['readback_matches_expected'] for row in done))
            r.close()

    def test_bad_bit_identified_without_stopping(self):
        for bit in range(8):
            with self.subTest(bit=bit), tempfile.TemporaryDirectory() as folder:
                r=Recorder(folder,{})
                m=MarkerOutput(r,{'test':255},transport=EightSerial(corrupt_bit=bit,after=128))
                m.send('test'); m.close()
                rows=[json.loads(row[0]) for row in r.db.execute("SELECT payload FROM records WHERE kind IN ('marker_ack','marker_done') ORDER BY id")]
                self.assertEqual(rows[0]['mismatched_output_pins'],[bit+2])
                self.assertEqual(rows[1]['mismatched_output_pins'],[9])
                self.assertFalse(rows[0]['readback_matches_expected'])
                r.close()


if __name__=='__main__': unittest.main()
