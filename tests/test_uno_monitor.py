import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gripflight.uno_monitor import plan_layout,series
from gripflight.grip import GripReader
from gripflight.input_devices.uno import UnoDevice

class UnoMonitorTests(unittest.TestCase):
    def test_single_screen_tiles_and_overrides_fullscreen(self):
        p=plan_layout([dict(width=1366,height=768)])
        self.assertFalse(p['fullscreen']);self.assertTrue(p['monitor_split'])
        self.assertEqual(p['screen'],0)
        self.assertLess(p['size'][0]+p['pos'][0],1366*.59)
        self.assertLessEqual(p['size'][1]+p['pos'][1],768)

    def test_external_screen_uses_nonprimary_even_when_primary_not_zero(self):
        screens=[dict(width=1920,height=1080),dict(width=1440,height=900)]
        p=plan_layout(screens,primary=1,preferred=1)
        self.assertEqual(p['screen'],0);self.assertTrue(p['fullscreen'])
        self.assertFalse(p['monitor_split'])
        self.assertEqual(p['size'],[1920,1080])
        p=plan_layout(screens,primary=0,preferred=7,windowed=True)
        self.assertEqual(p['screen'],1);self.assertFalse(p['fullscreen'])

    def test_relative_preserves_excess_negative_and_missing_samples(self):
        absolute,relative=series([(0,1),(1,4),(2,None),(3,0)],[1,3])
        self.assertEqual(relative,[(0,0),(1,150),(2,None),(3,-50)])
        self.assertEqual(series([(0,1)],None)[1],[(0,None)])

    def test_history_does_not_drain_capture_or_task_queue(self):
        recorder=Mock();recorder.now.return_value=0;recorder.record.return_value=7
        reader=GripReader(recorder,simulate=True,ordered=True)
        reader.start_capture();reader.begin_task()
        reader.accept(b'25,1,0,0\n',received_at=0)
        reader.accept(b'25,2,1,3906\n',received_at=.004)
        self.assertEqual(reader.monitor_history(),[(0,1,1),(.004,2,2)])
        self.assertEqual(reader.monitor_history(),[(0,1,1),(.004,2,2)])
        self.assertEqual(len(reader.drain_capture()),2)
        self.assertEqual(len(reader.take_samples()),2)

    def test_monitor_reference_only_after_calibration_or_loaded_profile(self):
        d=UnoDevice(dict(task=dict(grip_min=1,grip_max=3),calibration=dict(debug_mode=False)),None,None)
        d.monitor=Mock();d.recorder=Mock();d.recorder.now.return_value=5
        d._publish_monitor('准备')
        self.assertIsNone(d.monitor.publish.call_args.args[3])
        d._calibration_setup=SimpleNamespace(data={'calibration':{'status':'complete'}})
        d._publish_monitor('校准完成')
        self.assertEqual(d.monitor.publish.call_args.args[3],[1,3])
        d._calibration_setup=None;d.calibration_id='loaded'
        d._publish_monitor('游戏')
        self.assertEqual(d.monitor.publish.call_args.args[3],[1,3])


    def test_a0_voltage_is_not_scaled_by_game_gain(self):
        absolute,relative=series([(0,9.218,4.609),(1,None,None)],[8,10])
        self.assertEqual(absolute,[(0,4.609),(1,None)])
        self.assertAlmostEqual(relative[0][1],60.9)
        self.assertIsNone(relative[1][1])
        self.assertEqual(round(absolute[0][1]*1023/5),943)
