import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from gripflight.calibration_profile import configure_mode, prepare_calibration, validate_reference, identity
from gripflight.input_devices.uno import UnoDevice
from gripflight.recording import Recorder
from gripflight.weights import WeightModel, evaluate, default_weights


class CalibrationProfileTests(unittest.TestCase):
    def device(self, directory, name='uno'):
        c=dict(participant='p1', calibration=dict(debug_mode=False), grip=dict(gain=1),
               serial_devices=dict(grip='uno1'), task=dict(grip_min=10., grip_max=110.),
               multichannel=dict(serial_number=None))
        d=SimpleNamespace(name=name, config=c, source_hand='left', display_hand='right',
            devices=SimpleNamespace(fallback_raw=0), recorder=Mock())
        d.model=WeightModel(dict(weights=default_weights(),lift_gain=140,reference_scale=1),lambda *a:1,Path(directory)/'weights.json')
        return d

    def setup(self,directory):
        return SimpleNamespace(data={'calibration':{'status':'pending'}}, save=Mock(),
            recorder=SimpleNamespace(directory=Path(directory)))

    def test_formal_overrides_old_disabled_and_debug_is_explicit(self):
        for debug,simulate in [(False,False),(True,False),(False,True)]:
            c={'calibration':{'enabled':False}}
            configure_mode(c,SimpleNamespace(debug=debug,simulate=simulate,calibration_file=None))
            self.assertEqual(c['calibration']['enabled'],not (debug or simulate))
        with self.assertRaises(ValueError):
            configure_mode({},SimpleNamespace(debug=True,simulate=False,calibration_file='saved.json'))

    def test_save_and_load_both_device_references(self):
        for name in ('uno','rx-g0505m'):
            with self.subTest(device=name), tempfile.TemporaryDirectory() as directory:
                d=self.device(directory,name);s=self.setup(directory)
                def calibrate(*a):
                    s.data['calibration']['status']='complete'
                    if name!='uno':d.model.calibrate([10]*25,[100]*25)
                d.calibrate=calibrate
                prepare_calibration(d,None,s)
                saved=Path(directory)/'calibration_profile.json'
                profile=json.loads(saved.read_text())
                self.assertTrue(profile['measured'])
                newdir=Path(directory)/'next';newdir.mkdir()
                new=self.device(newdir,name);new.config['calibration']['source_file']=str(saved)
                new.calibrate=Mock(side_effect=AssertionError('Must not remeasure'))
                setup=self.setup(newdir)
                prepare_calibration(new,None,setup)
                self.assertEqual(new.calibration_id,d.calibration_id)
                self.assertEqual(setup.data['calibration']['status'],'loaded')
                self.assertEqual(json.loads((newdir/'calibration_profile.json').read_text()),profile)
                if name!='uno':self.assertEqual(new.model.snapshot()['baseline_g'],[10]*25)

    def test_formal_cannot_continue_when_calibration_is_disabled_or_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self.device(tmp);s=self.setup(tmp);d.calibrate=Mock()
            with self.assertRaises(RuntimeError):prepare_calibration(d,None,s)
            self.assertFalse((Path(tmp)/'calibration_profile.json').exists())

    def test_reuse_checks_identity_and_invalid_ranges(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self.device(tmp)
            p=dict(schema_version=1,measured=True,calibration_id='id',identity=identity(d),reference=dict(minimum=10,maximum=100))
            validate_reference(p,d)
            for key,value in [('participant','other'),('device','rx-g0505m'),('gain',2)]:
                bad=copy.deepcopy(p);bad['identity'][key]=value
                with self.assertRaises(ValueError):validate_reference(bad,d)
            for value in (10,float('nan'),float('inf')):
                bad=copy.deepcopy(p);bad['reference']['maximum']=value
                with self.assertRaises(ValueError):validate_reference(bad,d)
            d.name='rx-g0505m';p['identity']=identity(d)
            p['reference']=dict(baseline_g=[0]*25,reference_ranges_g=[0]*25)
            with self.assertRaises(ValueError):validate_reference(p,d)
            p['reference']['reference_ranges_g']=[100]*24
            with self.assertRaises(ValueError):validate_reference(p,d)

    def test_uno_preserves_over_100_percent_and_invalid_is_missing(self):
        d=UnoDevice(dict(task=dict(grip_min=10,grip_max=110,lift_gain=140)),None,None)
        d.calibration_id='measured'
        result=d.convert(dict(raw=160,valid=True,record_id=1,t=0))
        self.assertEqual(result.normalized,1)
        self.assertEqual(result.metrics['absolute_value'],160)
        self.assertEqual(result.metrics['percent_calibrated'],150)
        invalid=d.convert(dict(raw=None,valid=False,record_id=2,t=None))
        self.assertIsNone(invalid.metrics['percent_calibrated'])
        d.calibration_id=None
        self.assertIsNone(d.convert(dict(raw=160,valid=True,record_id=3,t=0)).metrics['relative_calibrated'])

    def test_rx_measurement_ratio_independent_of_game_reference_scale(self):
        model=WeightModel(dict(weights=[1]*25,lift_gain=140,reference_scale=2),lambda *a:1,'unused')
        self.assertIsNone(evaluate([160]*25,model.snapshot())['relative_calibrated'])
        model.calibrate([10]*25,[100]*24+[0])
        r=evaluate([160]*24+[10],model.snapshot())
        self.assertAlmostEqual(r['relative_calibrated'],1.5)
        self.assertAlmostEqual(r['normalized'],.75)
        self.assertEqual(r['channel_relative_calibrated'][:24],[1.5]*24)
        self.assertIsNone(r['channel_relative_calibrated'][24])

    def test_debug_never_writes_measured_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            d=self.device(tmp);d.config['calibration']['debug_mode']=True;d.calibrate=Mock()
            s=self.setup(tmp);prepare_calibration(d,None,s)
            self.assertEqual(s.data['calibration']['status'],'debug_skipped')
            self.assertIsNone(d.calibration_id)
            self.assertFalse((Path(tmp)/'calibration_profile.json').exists())

    def test_csv_exports_relative_and_absolute_fields(self):
        import csv
        with tempfile.TemporaryDirectory() as tmp:
            r=Recorder(tmp,{})
            r.record('task',dict(absolute_value=160,relative_calibrated=1.5,percent_calibrated=150,
                                point_01_g=160,point_01_relative=1.5,calibration_id='id'))
            r.close()
            with (r.directory/'task.csv').open(encoding='utf-8-sig') as f:row=next(csv.DictReader(f))
            self.assertEqual(row['percent_calibrated'],'150')
            self.assertEqual(row['point_01_relative'],'1.5')
            self.assertEqual(row['absolute_value'],'160')
