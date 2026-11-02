import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from gripflight.uno_feedback import feedback_scale,orb_amount,OrbMotion,phase_color
from gripflight.display import Display
from gripflight.input_devices.uno_calibration import run_calibration
from tests.test_calibration import FakeRecorder,FakeDisplay,FakeGrip,config

class OrbFeedbackTests(unittest.TestCase):
    def test_response_is_monotonic_without_a_full_threshold(self):
        scale=feedback_scale(.8,1)
        values=[orb_amount(v,.8,scale) for v in (.7,.8,.9,1.5,5,100)]
        self.assertEqual(values[:2],[0,0])
        self.assertEqual(values,sorted(values))
        self.assertTrue(all(0<=v<1 for v in values))
        self.assertEqual(orb_amount(None,.8,scale),0)
        self.assertEqual(orb_amount(1,None,scale),0)

    def test_fixed_scale_works_for_high_baseline_and_gain(self):
        self.assertGreater(feedback_scale(5,1),0)
        self.assertAlmostEqual(orb_amount(2.4,1.6,feedback_scale(1.6,2)),orb_amount(1.2,.8,feedback_scale(.8,1)))

    def test_orb_branch_updates_monitor_and_never_creates_progress_bar(self):
        d=Display.__new__(Display);d.uno_orb_feedback={'phase':'squeeze_1'}
        d.calibration_observer=Mock();d._uno_orb_renderer=Mock()
        d.draw_calibration('握紧','第1次',.9)
        d.calibration_observer.assert_called_once_with('握紧')
        d._uno_orb_renderer.draw.assert_called_once_with('握紧','第1次',d.uno_orb_feedback)
        self.assertFalse(hasattr(d,'cal_track'))

    def test_all_attempts_use_zero_based_fixed_display_scale(self):
        r=FakeRecorder()
        class CaptureDisplay(FakeDisplay):
            def draw_calibration(self,*args):
                self.states=getattr(self,'states',[])+[dict(self.uno_orb_feedback)]
                super().draw_calibration(*args)
        d=CaptureDisplay(r);c=config();c['calibration']['rest_s']=.3
        setup=SimpleNamespace(data={'calibration':{'segments':[]}},save=lambda:None)
        run_calibration(d,FakeGrip(r),r,c,setup)
        attempts=[s for s in d.states if s['phase'].startswith('squeeze')]
        self.assertEqual({s['phase'] for s in attempts},{'squeeze_1','squeeze_2','squeeze_3'})
        self.assertEqual({s['baseline'] for s in attempts},{.8})
        self.assertEqual({s['scale'] for s in attempts},{feedback_scale(.8,1)})
        self.assertEqual(d.states[-1]['peaks'],[1.1,1.2,1.3])
        self.assertEqual(setup.data['calibration']['reference']['reference_max_raw'],1.3)


class OrbMotionTests(unittest.TestCase):
    def test_release_is_continuous_and_finishes_within_one_second(self):
        for fps in (30, 60, 144):
            motion=OrbMotion()
            motion.update(1,0)
            for i in range(1,fps+1): motion.update(1,i/fps)
            before=motion.value
            first=motion.update(0,1+1/fps)
            self.assertGreater(first,0)
            self.assertLess(first,before)
            values=[motion.update(0,1+i/fps) for i in range(2,fps+1)]
            self.assertEqual(values,sorted(values,reverse=True))
            self.assertEqual(values[-1],0)

    def test_growth_is_gradual_and_no_force_stays_small(self):
        m=OrbMotion();m.update(0,0)
        self.assertEqual(m.update(0,1),0)
        self.assertGreater(m.update(1,1.016),0)
        self.assertLess(m.value,.5)
        self.assertGreater(m.update(1,1.5),.9)

    def test_rest_gray_squeeze_red(self):
        for phase in ('recovery',):
            r,g,b=phase_color(phase);self.assertGreater(g,max(r,b))
        for phase in ('zero','rest_1','rest_2'):
            r,g,b=phase_color(phase);self.assertEqual(r,g);self.assertEqual(g,b)
        for phase in ('squeeze_1','squeeze_2','squeeze_3'):
            r,g,b=phase_color(phase);self.assertGreater(r,max(g,b))
