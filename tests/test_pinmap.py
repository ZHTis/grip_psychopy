import json
import tempfile
import unittest
from gripflight.markers import MarkerOutput
from gripflight.recording import Recorder
from tests.test_eight_feedback import EightSerial


class PinMapTests(unittest.TestCase):
    def test_custom_order_reports_actual_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Recorder(folder,{})
            m=MarkerOutput(r,{'a':1},transport=EightSerial(corrupt_bit=0))
            m._pin_map('PINS,9,8,7,6,5,4,3,2,19,18,17,16,15,14,12,13')
            m.send('a'); m.close()
            row=json.loads(r.db.execute("SELECT payload FROM records WHERE kind='marker_ack'").fetchone()[0])
            self.assertEqual(row['mismatched_output_pins'],[9])
            self.assertEqual(row['mismatched_feedback_pins'],[19])
            self.assertEqual(row['mapping_source'],'firmware')
            r.close()

    def test_invalid_mapping_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Recorder(folder,{})
            m=MarkerOutput(r,{'a':1},simulate=True)
            for line in ['PINS,2,3', 'PINS,2,3,4,5,6,7,8,9,2,15,16,17,18,19,12,13',
                         'PINS,0,3,4,5,6,7,8,9,14,15,16,17,18,19,12,13']:
                with self.assertRaises(ValueError): m._pin_map(line)
            m.close(); r.close()


if __name__=='__main__': unittest.main()
