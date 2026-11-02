import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gripflight.input_devices.uno import UnoDevice
from gripflight.input_devices.uno_calibration import calibration_keys
from gripflight.calibration import CalibrationAborted
from gripflight.grip import GripReader
from gripflight.runner import game_loop


class EscapeTests(unittest.TestCase):
    def test_calibration_accepts_escape_from_either_window_and_keeps_space(self):
        for keys,abort in [(['escape'],False),([],True)]:
            d=SimpleNamespace(event=SimpleNamespace(getKeys=lambda: keys),abort_requested=lambda:abort)
            with self.assertRaises(CalibrationAborted):calibration_keys(d)
        d=SimpleNamespace(event=SimpleNamespace(getKeys=lambda:['space']))
        self.assertEqual(calibration_keys(d),['space'])

    def test_device_monitor_abort_is_latched_across_game_and_calibration(self):
        device=UnoDevice({},None,None)
        event=threading.Event();device.monitor=SimpleNamespace(abort=event)
        self.assertFalse(device.stop_requested)
        event.set()
        self.assertTrue(device.stop_requested)
        with self.assertRaises(CalibrationAborted):device._check_abort()

    def test_device_stimulus_escape_latched_during_startup(self):
        device=UnoDevice({},None,None)
        device.display=SimpleNamespace(event=SimpleNamespace(getKeys=lambda:['escape']))
        with self.assertRaises(CalibrationAborted):device._check_abort()
        device.display=None
        self.assertTrue(device.stop_requested)

    def test_waiting_for_silent_serial_can_abort_without_timeout(self):
        reader=GripReader(Mock(),simulate=True)
        def cancel():raise CalibrationAborted()
        with self.assertRaises(CalibrationAborted):reader.wait_ready(timeout=30,check_abort=cancel)

    def test_game_honors_curve_abort_without_reading_more_serial(self):
        device=UnoDevice({},None,None);event=threading.Event();event.set()
        device.monitor=SimpleNamespace(abort=event)
        device.read_inputs=Mock(side_effect=AssertionError('Must not continue reading'))
        devices=Mock()
        status=game_loop(None,device,None,devices,Mock(),{'markers':{'codes':{'abort':255}}},False)
        self.assertEqual(status,'aborted')
        devices.send.assert_called_once_with('abort',255,reason='user_stop')
        device.read_inputs.assert_not_called()
