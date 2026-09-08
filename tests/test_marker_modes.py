import json
import tempfile
import unittest
from gripflight.markers import MarkerOutput, encode_marker
from gripflight.recording import Recorder


class ModeSerial:
    def __init__(self): self.buffer, self.commands = bytearray(), []
    def write(self, packet):
        command,eid,code,width=packet.decode().strip().split(',')
        self.commands.append(command)
        during=f'B8,{code}' if command=='M' else 'OUT,-'
        after='B8,0' if command=='M' else 'OUT,-'
        self.buffer.extend(f'ACK,{eid},{code},100,{during}\nDONE,{eid},{code},10100,{after}\n'.encode())
        return len(packet)
    def read(self,n):
        result=bytes(self.buffer[:n]); del self.buffer[:n]; return result
    def close(self): pass


class ModeTests(unittest.TestCase):
    def test_both_modes_preserve_events_without_fabricating_readback(self):
        for mode,command in [('loopback','M'),('output_only','O')]:
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                r=Recorder(folder,{})
                s=ModeSerial()
                m=MarkerOutput(r,{'start':5},transport=s,mode=mode)
                m.send('start'); m.close()
                self.assertEqual(s.commands,[command])
                rows=[json.loads(row[0]) for row in r.db.execute("SELECT payload FROM records WHERE kind IN ('marker_ack','marker_done') ORDER BY id")]
                self.assertEqual(len(rows),2)
                if mode=='output_only':
                    self.assertTrue(all(row['feedback_mode']=='disabled' and row['readback_code'] is None and row['readback_matches_expected'] is None for row in rows))
                else:
                    self.assertTrue(all(row['readback_matches_expected'] for row in rows))
                r.close()

    def test_invalid_mode_rejected(self):
        with self.assertRaises(ValueError): encode_marker(1,5,10,'typo')
        self.assertEqual(encode_marker(1,5,10,'output_only'),b'O,1,5,10\n')


if __name__=='__main__': unittest.main()
