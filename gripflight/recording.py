"""Independent, thread-safe session recorder. SQLite is the authoritative record."""
import csv
import json
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class Recorder:
    def __init__(self, root, parameters):
        self.directory = Path(root) / (datetime.now().strftime('%Y%m%d_%H%M%S_') + uuid4().hex[:8])
        self.directory.mkdir(parents=True, exist_ok=False)
        self.lock = threading.RLock()
        self.origin = time.perf_counter()
        self.context = {'trial': 0, 'block': 1, 'phase': 'idle'}
        self.last_marker_id = None
        self.last_marker_code = None
        self.closed = False
        self.db = sqlite3.connect(self.directory / 'session.sqlite3', check_same_thread=False)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
            CREATE TABLE records(id INTEGER PRIMARY KEY, kind TEXT NOT NULL,
                t REAL NOT NULL, trial INTEGER, block INTEGER, phase TEXT,
                last_marker_id INTEGER, last_marker_code INTEGER, payload TEXT NOT NULL);
            CREATE INDEX by_kind_time ON records(kind,t);
        ''')
        metadata = {'schema_version': 1, 'utc_start': datetime.now(timezone.utc).isoformat(),
                    'clock': 'time.perf_counter seconds relative to session origin',
                    'parameters': parameters, 'status': 'recording'}
        self.metadata = metadata
        self._metadata()

    def now(self):
        return time.perf_counter() - self.origin

    def _metadata(self):
        temporary = self.directory / 'metadata.tmp'
        temporary.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.directory / 'metadata.json')

    def set_context(self, **context):
        with self.lock:
            self.context.update(context)

    def record(self, kind, payload, t=None):
        with self.lock:
            if self.closed:
                raise RuntimeError('Recorder already closed')
            c = self.context
            cursor = self.db.execute(
                'INSERT INTO records(kind,t,trial,block,phase,last_marker_id,last_marker_code,payload) VALUES(?,?,?,?,?,?,?,?)',
                (kind, self.now() if t is None else t, c['trial'], c['block'], c['phase'],
                 self.last_marker_id, self.last_marker_code, json.dumps(payload, ensure_ascii=False, allow_nan=False)))
            if kind == 'marker_request':
                self.last_marker_id = cursor.lastrowid
                self.last_marker_code = payload['code']
            return cursor.lastrowid

    def flush(self):
        with self.lock:
            self.db.commit()

    def export(self):
        """CSV keeps all fields; event CSV is the lossless marker channel alongside grip."""
        with self.lock:
            self.db.commit()
            exports = {'grip': ['grip', 'grip_invalid'],
                                'events': ['marker_request', 'marker_ack', 'marker_done', 'marker_error', 'event'],
                                'task': ['task'], 'trials': ['trial'], 'diagnostics': ['diagnostic'], 'grip_sync': ['grip_sync']}
            # Only add these exports to sessions containing the new device.
            if self.db.execute("SELECT 1 FROM records WHERE kind LIKE 'grip_multichannel%' LIMIT 1").fetchone():
                exports.update({name: [name] for name in (
                    'grip_multichannel', 'grip_multichannel_bytes', 'grip_multichannel_summary')})
            if self.db.execute("SELECT 1 FROM records WHERE kind='weight_update' LIMIT 1").fetchone():
                exports['weight_updates'] = ['weight_update']
            for name, kinds in exports.items():
                flat_columns = {
                    'weight_updates': ['revision', 'reason', 'lift_gain', 'reference_scale', 'calibrated'],
                    'grip_multichannel': ['hand', 'hand_code', 'received_index', 'host_unix_s',
                        'acquisition_id', 'valid', 'simulated', 'device_timed', 'device_sequence',
                        'device_micros', 'frame_hex'] + [f'point_{i:02d}_g' for i in range(1, 26)],
                    'grip_multichannel_bytes': ['acquisition_id', 'host_unix_s', 'byte_count', 'chunk_hex', 'simulated'],
                    'grip_multichannel_summary': ['acquisition_id', 'bytes_received', 'valid_frames',
                        'checksum_errors', 'discarded_bytes', 'pending_bytes', 'queued_frames', 'simulated'],
                    'grip': ['temperature', 'voltage', 'raw', 'line', 'error', 'valid', 'device_timed', 'device_sequence', 'device_micros', 'acquisition_id', 'simulated'],
                    'events': ['name', 'event_id', 'code', 'pulse_ms', 't_write_host_s',
                               'device_micros', 'simulated', 'error', 'a0_adc', 'loopback_pin',
                               'a0_expected_high', 'a0_measured_high', 'a0_matches_expected',
                               'mode', 'feedback_mode', 'readback_code', 'expected_readback_code', 'readback_bits',
                               'mismatch_mask', 'readback_matches_expected', 'mismatched_output_pins',
                               'mismatched_feedback_pins', 'output_pins', 'feedback_pins', 'mapping_source'],
                    'task': ['tick', 'game_phase', 'x', 'y', 'vy', 'raw', 'normalized', 'smoothed',
                             'result', 'collision_object', 'reason', 'grip_sample_id', 'scheduled_lateness_s', 'grip_valid', 'grip_device_sequence', 'grip_acquisition_id', 'task_use_host_s', 'grip_task_used', 'grip_age_s', 'input_reused', 'input_hand', 'display_hand', 'input_normalized', 'weight_revision', 'weighted_g', 'reference_g', 'lift_gain', 'applied_lift',
                             'calibration_id', 'calibration_valid', 'debug_mode', 'absolute_value', 'absolute_unit',
                             'baseline_value', 'calibration_range', 'relative_calibrated', 'percent_calibrated'] +
                            [f'point_{i:02d}_g' for i in range(1,26)] + [f'point_{i:02d}_relative' for i in range(1,26)],
                    'trials': ['result', 'reason', 'feedback_steps', 'x', 'y', 'collision_object'],
                    'diagnostics': ['error'],
                    'grip_sync': ['acquisition_id', 'sync_id', 'host_t1_s', 'host_t4_s', 'device_t2_us', 'device_t3_us'],
                }[name]
                rows = self.db.execute('SELECT * FROM records WHERE kind IN (' +
                                       ','.join('?' for _ in kinds) + ') ORDER BY t,id', kinds)
                with (self.directory / (name + '.csv')).open('w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f)
                    writer.writerow(['id', 'kind', 't_host_s', 'trial', 'block', 'phase',
                                     'last_marker_request_id', 'last_marker_code', 'payload_json'] + flat_columns)
                    for row in rows:
                        payload = json.loads(row[-1])
                        if name == 'grip_multichannel':
                            payload.update({f'point_{i:02d}_g': value
                                            for i, value in enumerate(payload['values_g'], 1)})
                        writer.writerow(list(row) + [payload.get(key) for key in flat_columns])

    def close(self, status='complete'):
        with self.lock:
            if self.closed:
                return
            self.export()
            self.metadata.update(status=status, duration_s=self.now())
            self._metadata()
            self.db.close()
            self.closed = True


def export_existing(directory):
    """Recover CSV after interruption without reopening acquisition."""
    r = Recorder.__new__(Recorder)
    r.directory = Path(directory)
    r.lock = threading.RLock()
    r.db = sqlite3.connect(r.directory / 'session.sqlite3')
    try:
        r.export()
    finally:
        r.db.close()
