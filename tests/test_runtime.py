import tempfile
import threading
import unittest
from unittest.mock import patch
from gripflight.runtime import ContinuingRecorder, ContinuingDevices


class RuntimeTests(unittest.TestCase):
    def test_missing_stale_recovery_and_reader_failure(self):
        with tempfile.TemporaryDirectory() as root:
            r = ContinuingRecorder(root, {})
            d = ContinuingDevices(r, .81)
            self.assertEqual(d.sample(1)['raw'], .81)
            class Grip:
                lock = threading.Lock()
                error = None
                latest_sample = {'raw': .94, 'record_id': 2, 't': -2}
            d.grip = Grip()
            self.assertEqual(d.sample(1)['input_status'], 'stale')
            self.assertEqual(d.sample(1)['raw'], .94)
            d.grip.latest_sample['t'] = r.now()
            self.assertEqual(d.sample(1)['input_status'], 'fresh')
            d.grip.error = IOError('disconnected')
            self.assertEqual(d.sample(1)['input_status'], 'reader_error')
            r.close('complete')

    def test_marker_failure_preserves_local_events(self):
        with tempfile.TemporaryDirectory() as root:
            r = ContinuingRecorder(root, {})
            d = ContinuingDevices(r, .81)
            class Marker:
                def check(self): raise IOError('bad ack')
            d.marker = Marker()
            d.send('start', 1)
            d.send('end', 2)
            self.assertEqual(r.backend.db.execute("SELECT count(*) FROM records WHERE kind='marker_request'").fetchone()[0], 2)
            self.assertEqual(r.backend.db.execute("SELECT count(*) FROM records WHERE kind='marker_ack'").fetchone()[0], 0)
            r.close('complete')

    def test_storage_failure_does_not_stop_task(self):
        with tempfile.TemporaryDirectory() as root:
            r = ContinuingRecorder(root, {})
            with patch.object(r.backend, 'record', side_effect=OSError('disk full')):
                self.assertIsNone(r.record('task', {}))
            self.assertEqual(r.dropped_records, 1)
            r.close('complete')


if __name__ == '__main__': unittest.main()
