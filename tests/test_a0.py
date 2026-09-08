import json
import tempfile
import unittest
from gripflight.markers import MarkerOutput
from gripflight.recording import Recorder


class FeedbackSerial:
    def __init__(self, during, after):
        self.during, self.after, self.buffer = during, after, bytearray()
    def write(self, packet):
        _, eid, code, width = packet.decode().strip().split(',')
        self.buffer.extend(f'ACK,{eid},{code},100,{self.during}\nDONE,{eid},{code},10100,{self.after}\n'.encode())
        return len(packet)
    def read(self, n):
        data=bytes(self.buffer[:n]); del self.buffer[:n]; return data
    def close(self): pass


class A0Tests(unittest.TestCase):
    def test_d4_on_off_and_failure_do_not_stop(self):
        for code, during, after, expected in [(4,1020,2,(True,True)), (1,3,2,(True,True)),
                                              (5,0,0,(False,True)), (255,1023,1023,(True,False))]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as folder:
                r=Recorder(folder,{})
                m=MarkerOutput(r,{'test':code},transport=FeedbackSerial(during,after),loopback_pin=4)
                m.send('test'); m.close()
                rows=[json.loads(x[0]) for x in r.db.execute("SELECT payload FROM records WHERE kind IN ('marker_ack','marker_done') ORDER BY id")]
                self.assertEqual(tuple(x['a0_matches_expected'] for x in rows),expected)
                self.assertEqual([x['a0_adc'] for x in rows],[during,after])
                r.close()

    def test_legacy_and_simulation_have_unknown_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Recorder(folder,{})
            m=MarkerOutput(r,{'test':4},simulate=True,loopback_pin=4)
            m.send('test'); m.close()
            self.assertIsNone(m._feedback(None,'ACK',4)['a0_matches_expected'])
            r.close()


if __name__=='__main__': unittest.main()
