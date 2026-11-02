import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

from gripflight.calibration import (CalibrationAborted, ExperimentSetup, reference,
                                   run_calibration, settings, summarize_segment)
from gripflight.grip import GripReader
from gripflight.runtime import ContinuingRecorder

ROOT = Path(__file__).resolve().parents[1]


def config():
    c = json.loads((ROOT/'config.json').read_text())
    c['runtime'] = {'simulate': True, 'headless': False}
    return c


def segment(phase, value, start=0, duration=1):
    return dict(phase=phase, start_s=start, end_s=start+duration,
                samples=[dict(t=start+i*.05, raw=value, voltage=value, record_id=i+1)
                         for i in range(round(duration/.05))])


class FakeRecorder:
    def __init__(self):
        self.clock = 0
        self.context = {}
        self.events = []
    def now(self): return self.clock
    def set_context(self, **context): self.context.update(context)
    def record(self, kind, payload, t=None):
        self.events.append((self.now(), kind, payload))
    def flush(self): pass


class FakeDisplay:
    def __init__(self, recorder, abort_at=None):
        self.recorder, self.abort_at = recorder, abort_at
        self.title = ''
        self.history = []
        self.callbacks = []
        self.win = SimpleNamespace(flip=self.flip, callOnFlip=lambda f:self.callbacks.append(f))
        self.event = SimpleNamespace(getKeys=self.keys, clearEvents=lambda:None)
        self.mouse = SimpleNamespace(getPressed=lambda:[False]*3)
    def flip(self):
        self.recorder.clock += .05
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks: callback()
    def draw_calibration(self, title, detail, progress):
        self.title = title
        self.history.append((title, detail, progress))
    def keys(self):
        if self.abort_at is not None and self.recorder.clock > self.abort_at:
            return ['escape']
        return ['space'] if self.title.startswith('校准完成') else []


class FakeGrip:
    simulate = False
    error = None
    def __init__(self, recorder): self.recorder = recorder
    def latest(self, max_age): return {'raw': .8, 't': self.recorder.now()}
    def start_capture(self): self.next = self.recorder.now()
    def drain_capture(self):
        samples = []
        phase = self.recorder.context['phase']
        value = {'calibration_zero': .8, 'calibration_squeeze_1': 1.1,
                 'calibration_squeeze_2': 1.2, 'calibration_squeeze_3': 1.3}[phase]
        while self.next < self.recorder.now():
            samples.append(dict(t=self.next, raw=value, voltage=value))
            self.next += .05
        return samples
    def stop_capture(self): return self.drain_capture()


class CalibrationTests(unittest.TestCase):
    def test_zero_three_peaks_and_lift_reference(self):
        c = config()
        segments = [segment('zero', .8)] + [segment(f'squeeze_{i}', v)
                    for i,v in enumerate([1.1,1.2,1.3],1)]
        values = reference(segments,c)
        self.assertEqual(values['zero_raw'], .8)
        self.assertEqual(values['reference_max_raw'],1.3)
        self.assertAlmostEqual(values['mean_peak_raw'],1.2)
        self.assertEqual(values['effective_lift_gain'], c['task']['lift_gain'])
        self.assertAlmostEqual(values['equilibrium_fraction'],c['task']['gravity']/c['task']['lift_gain'])
        c['calibration'].update(lift_mode='target_fraction', target_fraction=.25)
        self.assertEqual(reference(segments,c)['effective_lift_gain'],c['task']['gravity']/.25)

    def test_reject_missing_gaps_and_no_contraction(self):
        c=config(); s=segment('zero',.8)
        s['samples']=s['samples'][:2]
        with self.assertRaises(ValueError): summarize_segment(s,settings(c))
        s=segment('zero',.8);s['samples']=s['samples'][:5]+s['samples'][-5:]
        with self.assertRaises(ValueError): summarize_segment(s,settings(c))
        segments=[segment('zero',.8)]+[segment(f'squeeze_{i}',.8) for i in range(1,4)]
        with self.assertRaises(ValueError): reference(segments,c)

    def test_capture_keeps_every_sample_not_only_latest(self):
        class Recorder:
            def now(self): return 0
            def record(self,*args): return 1
        grip=GripReader(Recorder(),simulate=True)
        grip.start_capture()
        for v in (.8,1.5,.9): grip.accept(f'25,{v}'.encode())
        self.assertEqual([s['voltage'] for s in grip.drain_capture()],[.8,1.5,.9])
        self.assertEqual(grip.drain_capture(),[])
        self.assertEqual(grip.stop_capture(),[])
        grip.accept(b'25,1.0')
        self.assertIsNone(grip.capture_samples)

    def test_full_flow_rest_timing_and_configuration(self):
        c=config(); r=FakeRecorder(); d=FakeDisplay(r)
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        run_calibration(d,FakeGrip(r),r,c,setup)
        cal=setup.data['calibration']
        self.assertEqual(cal['status'],'complete')
        self.assertEqual(len(cal['segments']),4)
        self.assertEqual(c['task']['grip_min'],.8)
        self.assertEqual(c['task']['grip_max'],1.3)
        starts={e['name']:t for t,_,e in r.events if e['name'].endswith('_start')}
        self.assertGreaterEqual(starts['calibration_squeeze_2_start']-starts['calibration_rest_1_start'],15)
        self.assertGreaterEqual(starts['calibration_squeeze_3_start']-starts['calibration_rest_2_start'],15)
        self.assertTrue(any(row[0]=='最大力度握紧' for row in d.history))

    def test_uno_default_durations_and_three_complete_windows(self):
        c=config(); self.assertEqual(c['calibration']['squeeze_s'],5)
        self.assertEqual(c['calibration']['rest_s'],15)
        r=FakeRecorder(); d=FakeDisplay(r)
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        run_calibration(d,FakeGrip(r),r,c,setup)
        for attempt in setup.data['calibration']['attempts']:
            self.assertEqual(attempt['status'],'valid')
            self.assertAlmostEqual(attempt['end_s']-attempt['start_s'],5)

    def test_failed_attempts_retry_and_only_three_valid_peaks_enter_reference(self):
        c=config(); c['calibration'].update(zero_s=.5,squeeze_s=1.5,rest_s=.3)
        r=FakeRecorder(); d=FakeDisplay(r,abort_at=30)
        class IntermittentGrip(FakeGrip):
            def __init__(self,r): super().__init__(r); self.counts={}; self.silent_until=0
            def start_capture(self):
                super().start_capture()
                self.phase=self.recorder.context['phase']
                self.counts[self.phase]=self.counts.get(self.phase,0)+1
                self.begin=self.next
                if self.phase=='calibration_squeeze_1' and self.counts[self.phase]==1:
                    self.silent_until=self.begin+1.2
            def drain_capture(self):
                samples=super().drain_capture()
                if self.phase=='calibration_squeeze_1' and self.counts[self.phase]==1:
                    samples=[s for s in samples if s['t']<self.begin+.2]
                if self.phase=='calibration_squeeze_2' and self.counts[self.phase]==1:
                    for s in samples: s.update(raw=.8,voltage=.8)
                return samples
            def latest(self,max_age):
                if self.recorder.now()<self.silent_until:
                    return {'raw':1.1,'t':self.begin+.15}  # repeated old frame cannot restore acquisition
                return super().latest(max_age)
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        run_calibration(d,IntermittentGrip(r),r,c,setup)
        cal=setup.data['calibration']; attempts=cal['attempts']
        self.assertEqual(cal['status'],'complete')
        self.assertEqual([s['status'] for s in attempts],['invalid','valid','invalid','valid','valid'])
        self.assertEqual(attempts[0]['invalid_reason'],'data_timeout')
        self.assertLess(attempts[0]['observed_end_s']-attempts[0]['start_s'],.8)
        self.assertGreater(attempts[0]['observed_end_s']-attempts[0]['samples'][-1]['t'],.5)
        self.assertGreater(len(attempts[0]['samples']),0)
        self.assertGreaterEqual(attempts[1]['start_s'],attempts[0]['start_s']+1.2+.3)
        self.assertEqual(attempts[2]['invalid_reason'],'no_valid_contraction')
        self.assertEqual([s['phase'] for s in cal['segments']],['zero','squeeze_1','squeeze_2','squeeze_3'])
        self.assertEqual(cal['reference']['peaks_raw'],[1.1,1.2,1.3])

    def test_no_new_samples_cannot_be_replaced_with_repeated_latest_and_escape_works(self):
        c=config();c['calibration'].update(zero_s=.5,squeeze_s=5,rest_s=.3)
        r=FakeRecorder();d=FakeDisplay(r,abort_at=2)
        class SilentGrip(FakeGrip):
            def drain_capture(self):
                samples=super().drain_capture()
                return [] if self.recorder.context['phase'].startswith('calibration_squeeze') else samples
            def latest(self,max_age): return {'raw':1.2,'t':0}
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        with self.assertRaises(CalibrationAborted):run_calibration(d,SilentGrip(r),r,c,setup)
        cal=setup.data['calibration']
        self.assertEqual(cal['status'],'aborted')
        self.assertEqual(len(cal['attempts']),1)
        self.assertEqual(cal['attempts'][0]['status'],'invalid')
        self.assertEqual([s['phase'] for s in cal['segments']],['zero'])
        self.assertNotIn('reference',cal)
        self.assertTrue(any('本次未计入' in row[0] for row in d.history))

    def test_escape_keeps_partial_calibration(self):
        c=config();r=FakeRecorder();d=FakeDisplay(r,abort_at=.8)
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        with self.assertRaises(CalibrationAborted): run_calibration(d,FakeGrip(r),r,c,setup)
        self.assertEqual(setup.data['calibration']['status'],'aborted')
        self.assertGreater(len(setup.data['calibration']['segments'][0]['samples']),0)

    def test_setup_is_self_contained_and_preserves_original(self):
        c=config(); original=copy.deepcopy(c)
        with tempfile.TemporaryDirectory() as tmp:
            recorder=ContinuingRecorder(Path(tmp),c)
            map_bytes=b'type,x,y,width,height,assetId\ntop,1,2,3,4,a\n'
            setup=ExperimentSetup(recorder,original,c,map_bytes,[])
            c['task']['grip_min']=.7
            setup.save()
            saved=json.loads(setup.path.read_text())
            self.assertEqual(saved['original_config'],original)
            self.assertEqual(saved['effective_config']['task']['grip_min'],.7)
            self.assertEqual(saved['map']['csv_text'].encode(),map_bytes)
            self.assertEqual(saved['map']['sha256'],hashlib.sha256(map_bytes).hexdigest())
            recorder.close('complete')


if __name__=='__main__': unittest.main()
