import copy
import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import urllib.error
import urllib.request

from gripflight.weights import REGIONS, WeightModel, TickClock, default_weights, evaluate, validate_profile
from gripflight.weight_panel import PanelState, WeightPanel
from gripflight.weighted_task import calibrate, resolve_receiver
from gripflight.recording import Recorder
from gripflight.task import Task
from gripflight.calibration import CalibrationAborted
from tests.test_calibration import FakeRecorder, FakeDisplay

ROOT = Path(__file__).resolve().parents[1]


def profile():
    return dict(weights=default_weights(), lift_gain=140, reference_scale=1)


class WeightsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.records = []
        def record(kind, payload):
            self.records.append((kind, copy.deepcopy(payload)))
            return len(self.records)
        self.model = WeightModel(profile(), record, Path(self.temp.name)/'weights.json')

    def test_initial_regions_partition_points_and_sum_to_one(self):
        self.assertEqual(sorted(n for *_, points in REGIONS for n in points), list(range(1,26)))
        weights = default_weights()
        self.assertAlmostEqual(sum(weights), 100)
        for _,_,total,points in REGIONS:
            self.assertAlmostEqual(sum(weights[n-1] for n in points), total)
            self.assertEqual(len(set(weights[n-1] for n in points)), 1)
        # The user's saved profile may legitimately differ from the initial regional preset.
        validate_profile(json.loads((ROOT/'right_hand_weights.json').read_text()))

    def test_baseline_clamp_normalization_and_rescaling(self):
        self.model.calibrate([100]*25, [1000]*25)
        snapshot = self.model.snapshot()
        self.assertAlmostEqual(evaluate([600]*25,snapshot)['normalized'], .5)
        self.assertEqual(evaluate([50]*25,snapshot)['normalized'], 0)
        self.assertEqual(evaluate([2100]*25,snapshot)['normalized'], 1)
        p=profile(); p['weights']=[w*7 for w in p['weights']]
        self.model.update(p)
        self.assertAlmostEqual(evaluate([600]*25,self.model.snapshot())['normalized'], .5)
        p['reference_scale']=2;self.model.update(p)
        self.assertAlmostEqual(evaluate([600]*25,self.model.snapshot())['normalized'], .25)

    def test_hot_weights_recompute_reference_and_change_physics(self):
        self.model.calibrate([100]*25,[1000,2000]+[0]*23)
        p=profile();p['weights']=[1,0]+[0]*23
        self.model.update(p)
        first=evaluate([600,500]+[100]*23,self.model.snapshot())
        p['weights']=[0,1]+[0]*23;self.model.update(p)
        second=evaluate([600,500]+[100]*23,self.model.snapshot())
        self.assertAlmostEqual(first['normalized'],.5)
        self.assertAlmostEqual(second['normalized'],.2)
        self.assertEqual(second['reference_g'],2000)
        config=json.loads((ROOT/'config_multichannel.json').read_text())['task']
        a,b=(Task(copy.deepcopy(config),[],1e6) for _ in range(2))
        for task,value in ((a,first),(b,second)):
            task.phase='feedback';task.tick(value['normalized'])
        self.assertGreater(a.vy,b.vy)
        self.assertEqual([s['revision'] for _,s in self.records],[0,1,2,3])

    def test_invalid_profile_and_dead_channels_do_not_replace_last_good(self):
        snapshot=self.model.snapshot()
        for weights in ([0]*25, [-1]+[1]*24, [float('nan')]+[1]*24, [1]*24, [True]*25):
            with self.assertRaises(ValueError): self.model.update(dict(profile(),weights=weights))
        self.assertEqual(self.model.snapshot(),snapshot)
        self.model.calibrate([0]*25,[1000]+[0]*24)
        with self.assertRaises(ValueError): self.model.update(dict(profile(),weights=[0,1]+[0]*23))
        self.assertEqual(self.model.snapshot()['revision'],1)

    def test_revision_guard_calibration_lock_and_logging_failure(self):
        with self.assertRaises(ValueError): self.model.update(profile(),expected_revision=9)
        self.model.locked=True
        with self.assertRaises(ValueError): self.model.update(profile())
        self.model.locked=False
        self.model.record=lambda *a:None
        with self.assertRaises(RuntimeError): self.model.update(profile())
        self.assertEqual(self.model.snapshot()['revision'],0)

    def test_saved_defaults_exclude_session_calibration(self):
        self.model.calibrate([25]*25,[750]*25)
        p=profile();p['weights'][0]=0;p['lift_gain']=150
        self.model.update(p);path=Path(self.model.save_profile())
        saved=json.loads(path.read_text())
        self.assertEqual(saved['weights'][0],0)
        self.assertNotIn('baseline_g',saved)
        self.assertEqual(saved['hand'],'right')
        reloaded=WeightModel(saved,lambda *a:1,path)
        self.assertFalse(reloaded.snapshot()['calibrated'])
        self.assertEqual(reloaded.snapshot()['baseline_g'],[0]*25)

    def test_fixed_clock_pause_and_stall(self):
        clock=TickClock(60);clock.advance(0)
        self.assertEqual(sum(clock.advance(n/120)[0] for n in range(1,121)),60)
        self.assertEqual(clock.advance(30,paused=True),(0,False))
        self.assertEqual(clock.advance(30+1/60),(1,False))
        self.assertEqual(clock.advance(60),(1,True))

    def test_profile_and_task_csv_keep_reconstructable_revision(self):
        r=Recorder(self.temp.name,{})
        m=WeightModel(profile(),r.record,Path(self.temp.name)/'p.json')
        values=[100+i*50 for i in range(25)]
        for index in range(3):
            if index: m.update(dict(profile(),weights=[index+1]+[1]*24))
            result=evaluate(values,m.snapshot())
            r.record('task',dict(result,input_reused=False,input_hand='right',lift_gain=140,applied_lift=result['lift']))
        r.close()
        with (r.directory/'weight_updates.csv').open(encoding='utf-8-sig') as f:
            snapshots={row['revision']:json.loads(row['payload_json']) for row in csv.DictReader(f)}
        with (r.directory/'task.csv').open(encoding='utf-8-sig') as f:
            tasks=list(csv.DictReader(f))
        self.assertEqual(len(tasks),3)
        for row in tasks:
            expected=evaluate(values,snapshots[row['weight_revision']])
            self.assertAlmostEqual(float(row['weighted_g']),expected['weighted_g'])

    def test_panel_http_mutations_validation_and_pause(self):
        state=PanelState(self.model,self.model.record);panel=WeightPanel(state)
        self.addCleanup(panel.close)
        base=panel.url.split('/?')[0]
        def request(path, body=None, token=panel.token, origin=None):
            headers={'X-Grip-Token':token,'Content-Type':'application/json'}
            if origin: headers['Origin']=origin
            req=urllib.request.Request(base+path,data=None if body is None else json.dumps(body).encode(),headers=headers)
            with urllib.request.urlopen(req,timeout=3) as resp:return json.load(resp)
        self.assertEqual(request('/state')['profile']['revision'],0)
        p=profile();p['weights'][0]=0;p['revision']=0
        self.assertEqual(request('/weights',p)['profile']['revision'],1)
        with self.assertRaises(urllib.error.HTTPError):request('/weights',p)
        self.assertTrue(request('/control',{'action':'pause'})['paused'])
        self.assertFalse(request('/control',{'action':'resume'})['paused'])
        with self.assertRaises(urllib.error.HTTPError):request('/control',{'action':'stop'},origin='https://example.org')
        with self.assertRaises(urllib.error.HTTPError):request('/state',token='wrong')
        self.assertFalse(state.stop)
        request('/save',{})
        self.assertTrue(self.model.profile_path.is_file())


class CalibrationRecorder(FakeRecorder):
    def record(self,*args,**kwargs):
        super().record(*args,**kwargs)
        return len(self.events)


class MultiReader:
    simulate=False
    def __init__(self,recorder,failed_squeeze=None):
        self.recorder=recorder;self.next=0;self.failed_squeeze=failed_squeeze
    def check(self):pass
    def latest(self,*args,**kwargs):return dict(values_g=[50]*25)
    def take_samples(self):
        phase=self.recorder.context.get('phase','')
        value=50
        if 'squeeze' in phase and phase != self.failed_squeeze:value=50+100*int(phase[-1])
        samples=[]
        while self.next < self.recorder.now():
            samples.append(dict(hand='left',t=self.next,values_g=[value+i for i in range(25)]))
            samples.append(dict(hand='right',t=self.next,values_g=[60000]*25))
            self.next+=.025
        return samples


class WeightedCalibrationTests(unittest.TestCase):
    def run_cal(self,abort_at=None,failed_squeeze=None):
        r=CalibrationRecorder();d=FakeDisplay(r,abort_at=abort_at)
        d.set_pressure=lambda values:None
        c=json.loads((ROOT/'config_multichannel.json').read_text());c['runtime']={'headless':False}
        c['calibration'].update(enabled=True,zero_s=.5,squeeze_s=.5,rest_s=.5)
        m=WeightModel(profile(),r.record,Path('/unused'))
        state=PanelState(m,r.record)
        setup=SimpleNamespace(data={'calibration':{}},save=lambda:None)
        self.parts=(r,d,m,state,setup)
        calibrate(d,MultiReader(r,failed_squeeze),m,state,r,c,setup)
        return self.parts
    def test_zero_and_three_peaks_all_channels(self):
        r,d,m,state,setup=self.run_cal()
        cal=setup.data['calibration']
        self.assertEqual(cal['status'],'complete')
        self.assertEqual(cal['baseline_g'],[50+i for i in range(25)])
        self.assertEqual(cal['three_peaks_g'],[[150+i for i in range(25)],[250+i for i in range(25)],[350+i for i in range(25)]])
        self.assertEqual(m.snapshot()['reference_ranges_g'],[300]*25)
        self.assertFalse(m.locked)
        self.assertTrue(any(row[0].startswith('校准完成') for row in d.history))
    def test_missing_squeeze_fails_without_accepting_calibration(self):
        with self.assertRaises(ValueError):self.run_cal(failed_squeeze='calibration_squeeze_2')
        r,d,m,state,setup=self.parts
        self.assertFalse(m.snapshot()['calibrated'])
        self.assertEqual(setup.data['calibration']['status'],'error')
        self.assertFalse(m.locked)
    def test_abort_preserves_partial_capture(self):
        with self.assertRaises(CalibrationAborted):self.run_cal(abort_at=.3)
        r,d,m,state,setup=self.parts
        self.assertEqual(setup.data['calibration']['status'],'aborted')
        self.assertGreater(len(setup.data['calibration']['segments'][0]['samples']),0)
        self.assertFalse(m.locked)

class WeightedRunTests(unittest.TestCase):
    def test_simulated_run_uses_live_revision_keeps_raw_frames_and_pause_events(self):
        import sys
        import time
        from unittest.mock import patch
        from gripflight import weighted_task
        from gripflight.input_devices import rx_g0505m
        states=[]
        class CapturedState(PanelState):
            def __init__(self,*args):
                super().__init__(*args);states.append(self)
        class Display:
            def __init__(self,*args):
                self.count=0;self.callbacks=[]
                self.win=SimpleNamespace(flip=self.flip,callOnFlip=lambda f,*a:self.callbacks.append((f,a)))
                self.event=SimpleNamespace(getKeys=lambda:[])
                self.mouse=SimpleNamespace(getPressed=lambda:[False]*3)
            def set_pressure(self,values):
                self.last_values=list(values)
            def draw(self,task):pass
            def close(self):pass
            def flip(self):
                time.sleep(.01);self.count+=1
                for f,a in self.callbacks:f(*a)
                self.callbacks=[]
                s=states[0]
                if self.count==20:s.model.update(dict(profile(),weights=[1]+[0]*24))
                if self.count==30:s.control('pause')
                if self.count==50:s.control('resume')
                if self.count==100:s.control('stop')
        with tempfile.TemporaryDirectory() as tmp:
            c=json.loads((ROOT/'config_multichannel.json').read_text())
            c['output']=tmp;c['calibration']['enabled']=False
            c['task']['durations'].update(pre_run=0,prepare=0,result=0,iti=0)
            config_path=Path(tmp)/'config.json';config_path.write_text(json.dumps(c))
            args=SimpleNamespace(config=str(config_path),weights=None,grip_port=None,
                simulate=True,markers_enabled=False,marker_mode=None,marker_port=None,
                fullscreen=False,windowed=False,no_weight_panel=True,headless=False)
            with patch.object(rx_g0505m,'PanelState',CapturedState),patch.dict(sys.modules,{'gripflight.pressure_display':SimpleNamespace(WeightedDisplay=Display)}):
                weighted_task.run(args)
            session=next(Path(tmp).glob('*/experiment_setup.json')).parent
            setup=json.loads((session/'experiment_setup.json').read_text())
            self.assertEqual(setup['status'],'aborted')
            self.assertEqual(setup['calibration']['status'],'debug_skipped')
            self.assertEqual(setup['calibration']['segments'],[])
            self.assertFalse(setup['weighted_input']['calibrated'])
            self.assertEqual(setup['weighted_input']['baseline_g'],[0]*25)
            self.assertEqual(setup['weighted_input']['reference_ranges_g'],[1000]*25)
            self.assertEqual(setup['weighted_input']['revision'],1)
            self.assertEqual(setup['hand_assignment']['source_hand'],'left')
            self.assertEqual(setup['hand_assignment']['display_hand'],'right')
            with (session/'grip_multichannel.csv').open(encoding='utf-8-sig') as f:raw={row['id']:row for row in csv.DictReader(f)}
            with (session/'task.csv').open(encoding='utf-8-sig') as f:tasks=list(csv.DictReader(f))
            self.assertEqual({row['weight_revision'] for row in tasks},{'0','1'})
            self.assertGreater(len(raw),10)
            for row in tasks:
                source=raw[row['grip_sample_id']]
                self.assertEqual(row['input_hand'],'left')
                self.assertEqual(row['display_hand'],'right')
                self.assertEqual(source['hand'],'left')
                if row['weight_revision']=='1':
                    self.assertAlmostEqual(float(row['weighted_g']),float(source['point_01_g']))
            with (session/'events.csv').open(encoding='utf-8-sig') as f:events=list(csv.DictReader(f))
            pause=next(float(row['t_host_s']) for row in events if row['name']=='panel_pause')
            resume=next(float(row['t_host_s']) for row in events if row['name']=='panel_resume')
            self.assertFalse(any(pause<float(row['t_host_s'])<resume for row in tasks))
            self.assertTrue(any(pause<float(row['t_host_s'])<resume for row in raw.values()))
            self.assertTrue(any(row['input_reused']=='True' for row in tasks))


if __name__=='__main__':unittest.main()
