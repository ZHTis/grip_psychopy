"""Regression coverage for the device boundary and shared session lifecycle."""
import copy
import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

from gripflight.input_devices.base import ControlInput, InputDevice
from gripflight.input_devices.uno import UnoDevice, normalize
from gripflight.input_devices.rx_g0505m import RXDevice
from gripflight.runner import advance_task, run
from gripflight.task import Task
from gripflight.weights import WeightModel, evaluate, default_weights, TickClock
from gripflight.weight_panel import PanelState

ROOT = Path(__file__).resolve().parents[1]


def args(config=None):
    return SimpleNamespace(config=config, grip_device='uno', weights=None, grip_port=None,
        marker_port=None, simulate=True, markers_enabled=False, marker_mode=None,
        fullscreen=False, windowed=True, no_weight_panel=True, headless=False, no_grip_monitor=True)


class Log:
    dropped_records = 0
    def __init__(self): self.rows=[]
    def now(self): return 10.0
    def set_context(self, **kw): pass
    def record(self, kind, data):
        self.rows.append((kind, data)); return len(self.rows)


class DeviceBoundaryTests(unittest.TestCase):
    def test_uno_conversion_preserves_original_abs_range_and_invalid_slot(self):
        c=json.loads((ROOT/'config.json').read_text())
        d=UnoDevice(c,args(),ROOT)
        for raw in (0, .81, 1, -1, 1.2, 4):
            s=d.convert(dict(raw=raw,valid=True,record_id=8,t=3.0,device_sequence=91,acquisition_id='acq'))
            expected=max(0,min(1,(abs(raw)-.81)/(1.2-.81)))
            self.assertAlmostEqual(s.normalized,expected)
            self.assertEqual(s.raw,abs(raw))
            self.assertEqual(s.record_fields(4)['grip_age_s'],1)
            self.assertEqual(s.device_sequence,91)
        missing=d.convert(dict(raw=None,valid=False,record_id=9,t=None,device_sequence=92,acquisition_id='acq'))
        self.assertFalse(missing.valid)
        self.assertIsNone(missing.record_fields(4)['grip_age_s'])
        for value in (float('nan'),float('inf')):
            with self.assertRaises(ValueError):normalize(value,.81,1.2)

    def test_same_effort_from_both_devices_has_identical_game_physics(self):
        c=json.loads((ROOT/'config.json').read_text())
        c['task'].update(gravity=0, lift_gain=.1, forward_speed=.01, smoothing=.35)
        c['task']['durations'].update(pre_run=0,prepare=0,feedback=10)
        uno=UnoDevice(c,args(),ROOT)
        model=WeightModel(dict(weights=default_weights(),lift_gain=.1,reference_scale=1),lambda *a:1,Path('/unused'))
        a,b=(Task(copy.deepcopy(c['task']),[],100000) for _ in range(2))
        # The core also works without any device-specific range fields.
        for task in (a,b):
            del task.c['grip_min'];del task.c['grip_max']
        ra,rb=Log(),Log()
        for i in range(120):
            level=(i%11)/10
            u=uno.convert(dict(raw=.81+level*(1.2-.81),valid=True,record_id=i,t=1))
            r=evaluate([level*1000]*25,model.snapshot())
            rx=ControlInput(r['normalized'],.1,raw=r['normalized'],sample_id=i,hand='right',weight_revision=0)
            advance_task(a,u,ra);advance_task(b,rx,rb)
            self.assertEqual(a.phase,b.phase)
            self.assertEqual(a.tick_index,b.tick_index)
            for key in ('x','y','vy','smoothed'):
                self.assertAlmostEqual(getattr(a,key),getattr(b,key),places=12)
            self.assertEqual([n for n,_ in a.take_events()],[n for n,_ in b.take_events()])
        self.assertNotEqual(ra.rows[-1][1]['raw'],rb.rows[-1][1]['raw'])

    def test_invalid_control_advances_time_but_never_physics(self):
        c=json.loads((ROOT/'config.json').read_text())['task']
        t=Task(c,[],100000);t.phase='feedback'
        before=(t.x,t.y,t.vy,t.feedback_steps)
        r=Log();advance_task(t,ControlInput(0,140,valid=False,sample_id=12,device_sequence=4),r)
        self.assertEqual((t.x,t.y,t.vy,t.feedback_steps),before)
        self.assertEqual(t.tick_index,1)
        row=r.rows[-1][1]
        self.assertFalse(row['grip_task_used']);self.assertFalse(row['grip_valid'])
        self.assertEqual(row['grip_sample_id'],12);self.assertEqual(row['grip_device_sequence'],4)

    def test_rx_has_no_dependency_on_uno_grip_settings(self):
        c=json.loads((ROOT/'config_multichannel.json').read_text())
        del c['grip']
        c['task'].pop('grip_min');c['task'].pop('grip_max')
        d=RXDevice(c,args(),ROOT);d.configure()
        self.assertEqual(d.name,'rx-g0505m')
        self.assertEqual(c['task']['sampling_rate'],60)
        self.assertFalse(c['calibration']['enabled'])

    def test_rx_left_device_drives_right_ui_and_reused_frames_are_explicit(self):
        c=json.loads((ROOT/'config_multichannel.json').read_text())
        d=RXDevice(c,args(),ROOT);d.configure();d.recorder=Log()
        d.model=WeightModel(d.profile,d.recorder.record,Path('/unused'))
        d.state=PanelState(d.model,d.recorder.record);d.clock=TickClock(60)
        class Reader:
            acquisition_id='rx-acq'
            only_right=False
            def take_samples(self):return []
            def latest(self,hand,max_age):
                if hand!='left':raise AssertionError('Wrong protocol hand requested')
                if self.only_right:raise RuntimeError('No fresh left frame')
                return dict(hand='left',values_g=[500]*25,t=1,record_id=99)
        d.reader=Reader()
        self.assertEqual(d.read_inputs(0,[],False),[])
        slots=d.read_inputs(2/60,[],False)
        self.assertEqual([s.reused for s in slots],[False,True])
        self.assertEqual([s.sample_id for s in slots],[99,99])
        self.assertEqual([s.hand for s in slots],['left','left'])
        self.assertEqual([s.metrics['display_hand'] for s in slots],['right','right'])
        d.state.paused=True
        self.assertEqual(d.read_inputs(3/60,[],False),[])
        d.reader.only_right=True
        with self.assertRaisesRegex(RuntimeError,'left'):d.read_inputs(4/60,[],False)

    def test_uno_simulation_runs_through_shared_loop_and_keeps_raw_links(self):
        class Display:
            def __init__(self,*a):
                self.count=0;self.callbacks=[]
                self.event=SimpleNamespace(getKeys=lambda:['escape'] if self.count>=50 else [])
                self.mouse=SimpleNamespace(getPressed=lambda:[self.count%20>=10,False,False])
                self.win=SimpleNamespace(flip=self.flip,callOnFlip=lambda f,*a:self.callbacks.append((f,a)))
            def draw(self,task):pass
            def flip(self):
                time.sleep(.01);self.count+=1
                callbacks,self.callbacks=self.callbacks,[]
                for f,a in callbacks:f(*a)
            def close(self):pass
        with tempfile.TemporaryDirectory() as tmp:
            c=json.loads((ROOT/'config.json').read_text())
            c['output']=tmp;c['calibration']['enabled']=False
            c['task']['durations'].update(pre_run=0,prepare=0)
            path=Path(tmp)/'config.json';path.write_text(json.dumps(c))
            with patch('gripflight.display.Display',Display):run(args(str(path)))
            session=next(Path(tmp).glob('*/experiment_setup.json')).parent
            setup=json.loads((session/'experiment_setup.json').read_text())
            self.assertEqual(setup['status'],'aborted')
            self.assertEqual(setup['device_input']['device'],'uno')
            self.assertEqual(setup['scalar_input']['minimum'],.81)
            with (session/'grip.csv').open(encoding='utf-8-sig') as f:raw={r['id']:r for r in csv.DictReader(f)}
            with (session/'task.csv').open(encoding='utf-8-sig') as f:rows=list(csv.DictReader(f))
            self.assertGreater(len(rows),30)
            self.assertEqual({float(r['input_normalized']) for r in rows},{0,1})
            for r in rows:
                source=raw[r['grip_sample_id']]
                self.assertEqual(r['grip_device_sequence'],source['device_sequence'])
                self.assertAlmostEqual(float(r['input_normalized']),normalize(float(source['raw']),.81,1.2))
                self.assertEqual(r['input_reused'],'False')
            with (session/'events.csv').open(encoding='utf-8-sig') as f:events=list(csv.DictReader(f))
            flips=[json.loads(r['payload_json'])['timing'] for r in events if r['kind']=='marker_request' and r['name']!='abort']
            self.assertTrue(flips);self.assertEqual(set(flips),{'callOnFlip'})

    def test_shared_runner_closes_resources_and_saves_error_on_device_failure(self):
        closed=[]
        class FailingDevice(InputDevice):
            name='fake';default_config='config.json'
            def configure(self):self.runtime={'control_clock':'test'};self.port=None
            def start(self,*a):raise RuntimeError('reader failed')
            def stop_controls(self):closed.append('controls')
            def close(self):closed.append('reader')
        with tempfile.TemporaryDirectory() as tmp:
            c=json.loads((ROOT/'config.json').read_text());c['output']=tmp
            path=Path(tmp)/'config.json';path.write_text(json.dumps(c))
            a=args(str(path));a.headless=True
            with patch('gripflight.runner.device_class',return_value=FailingDevice):
                with self.assertRaisesRegex(RuntimeError,'reader failed'):run(a)
            setup=json.loads(next(Path(tmp).glob('*/experiment_setup.json')).read_text())
            self.assertEqual(setup['status'],'error')
            self.assertEqual(closed,['controls','reader'])
            self.assertEqual(setup['device_input']['device'],'fake')


if __name__=='__main__':unittest.main()
