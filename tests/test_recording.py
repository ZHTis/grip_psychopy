import csv
import json
import sqlite3
import tempfile
import threading
import unittest
from gripflight.recording import Recorder, export_existing


class RecordingTests(unittest.TestCase):
    def test_concurrent_lossless_and_event_link(self):
        with tempfile.TemporaryDirectory() as root:
            r = Recorder(root, {'participant': 'test', 'parameter': 1.2})
            r.set_context(trial=3, phase='feedback')
            event_id = r.record('marker_request', {'code': 128})
            threads = [threading.Thread(target=lambda: [r.record('grip', {'voltage': .91}) for _ in range(100)]) for _ in range(3)]
            for t in threads: t.start()
            for t in threads: t.join()
            directory = r.directory
            r.close()
            with sqlite3.connect(directory/'session.sqlite3') as db:
                rows = db.execute("SELECT trial,last_marker_id FROM records WHERE kind='grip'").fetchall()
            db.close()
            self.assertEqual(len(rows), 300)
            self.assertTrue(all(row == (3, event_id) for row in rows))
            with (directory/'grip.csv').open(encoding='utf-8-sig') as f:
                exported = list(csv.DictReader(f))
                self.assertEqual(len(exported), 300)
                self.assertTrue(all(row['voltage'] == '0.91' and row['last_marker_code'] == '128' for row in exported))
            self.assertEqual(json.loads((directory/'metadata.json').read_text())['parameters']['parameter'], 1.2)
            export_existing(directory)

    def test_unique_sessions_and_post_close_failure(self):
        with tempfile.TemporaryDirectory() as root:
            a, b = Recorder(root, {}), Recorder(root, {})
            self.assertNotEqual(a.directory, b.directory)
            a.close('aborted'); b.close()
            with self.assertRaises(RuntimeError): a.record('grip', {})


if __name__ == '__main__': unittest.main()
