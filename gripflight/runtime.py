"""Task-only continuation policy. Independent bench tests remain strict."""
import time
from .recording import Recorder
from .event_log import EventHistory, WATCHED


class ContinuingRecorder:
    def __init__(self, root, parameters):
        self.event_history = EventHistory()
        self.origin = time.perf_counter()
        self.backend = None
        self.directory = root
        self.warnings = {}
        self.dropped_records = 0
        try:
            self.backend = Recorder(root, parameters)
            self.directory = self.backend.directory
        except Exception as exc:
            self.warn('storage', exc)

    def now(self):
        return self.backend.now() if self.backend else time.perf_counter()-self.origin

    def warn(self, category, exc):
        message = str(exc)
        if self.warnings.get(category) != message:
            print(f'WARNING [{category}]: {message}; task continues', flush=True)
        self.warnings[category] = message

    def record(self, kind, payload, t=None):
        watched = kind in WATCHED
        if watched and t is None:
            t = self.now()
        record_id = None
        try:
            if self.backend:
                record_id = self.backend.record(kind, payload, t)
        except Exception as exc:
            self.warn('storage', exc)
        if watched:
            self.event_history.append(kind, payload, t, record_id)
        if record_id is None:
            self.dropped_records += 1
        return record_id

    def recent_events(self):
        return self.event_history.snapshot()

    def set_context(self, **context):
        if self.backend:
            self.backend.set_context(**context)

    def flush(self):
        if self.backend:
            try:
                self.backend.flush()
            except Exception as exc:
                self.warn('storage', exc)

    def close(self, status):
        if self.backend:
            self.backend.metadata.update(runtime_warnings=self.warnings,
                                         dropped_records=self.dropped_records)
            try:
                self.backend.close(status)
            except Exception as exc:
                self.warn('storage_close', exc)
        if self.warnings or self.dropped_records:
            print('Session has warnings; completion does not imply complete hardware/data recording.', flush=True)


class ContinuingDevices:
    def __init__(self, recorder, fallback_raw, markers_enabled=True):
        self.recorder, self.fallback_raw = recorder, fallback_raw
        self.grip = self.marker = None
        self.markers_enabled = markers_enabled
        self.marker_failed = False
        self.last_grip_state = None

    def warning(self, category, error):
        self.recorder.warn(category, error)
        self.recorder.record('diagnostic', {'category': category, 'error': str(error), 'continued': True})

    def sample(self, max_age):
        sample = None
        error = None
        if self.grip:
            with self.grip.lock:
                if self.grip.latest_sample:
                    sample = dict(self.grip.latest_sample)
            error = self.grip.error
        age = self.recorder.now()-sample['t'] if sample else None
        state = 'missing' if sample is None else ('reader_error' if error else ('stale' if age > max_age else 'fresh'))
        if state != self.last_grip_state:
            self.recorder.record('diagnostic', {'category': 'grip_status', 'state': state, 'age_s': age, 'continued': True})
            if state != 'fresh':
                self.recorder.warn('grip', f'{state}: holding last valid value, or grip_min if none')
            self.last_grip_state = state
        if sample is None:
            sample = {'raw': self.fallback_raw, 'record_id': None, 't': None}
        sample.update(input_status=state, age_s=age)
        return sample

    def check_marker(self):
        if self.marker and not self.marker_failed:
            try:
                self.marker.check()
            except Exception as exc:
                self.marker_failed = True
                self.warning('marker', exc)

    def send(self, name, code, **details):
        if not self.markers_enabled:
            return self.recorder.record('marker_request', dict(name=name, code=code,
                output_available=False, hardware_output_enabled=False,
                local_only=True, **details))
        self.check_marker()
        if self.marker and not self.marker_failed:
            try:
                return self.marker.send(name, **details)
            except Exception as exc:
                self.marker_failed = True
                self.warning('marker', exc)
        event_id = self.recorder.record('marker_request', dict(name=name, code=code,
            output_available=False, **details))
        self.recorder.record('marker_error', {'event_id': event_id, 'code': code,
            'error': 'Output unavailable; event saved locally only'})
        return event_id
