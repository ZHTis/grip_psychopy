import tempfile
import unittest
from gripflight.grip import GripReader, parse_line
from gripflight.recording import Recorder
from gripflight.timing import export_session, fit_clock
from test_grip import FakeSerial
import test_task
from gripflight.task import Task

class TimedGripTests(unittest.TestCase):
    def test_strict_parser(self):
        self.assertEqual(parse_line('0,1.25,4294967295,12', require_timing=True)['device_sequence'], 4294967295)
        for line in ['0,1', '0,1,-1,3', '0,1,4294967296,3', '0,nan,1,2', '0,1,1.0,2']:
            with self.assertRaises(ValueError): parse_line(line, require_timing=True)

    def test_order_gap_wrap_sync_and_export(self):
        with tempfile.TemporaryDirectory() as folder:
            r=Recorder(folder,{})
            g=GripReader(r, transport=FakeSerial([]), require_timing=True, ordered=True)
            g.begin_task()
            g.accept(b'0,1,4294967295,4294964000', 0)
            g.accept(b'0,2,1,4516', .01)
            samples=g.take_samples()
            self.assertEqual([s['device_sequence'] for s in samples],[4294967295,0,1])
            self.assertEqual([s['valid'] for s in samples],[True,False,True])
            self.assertIsNone(samples[1]['t'])
            self.assertEqual(g.take_samples(),[])
            g.pending_sync[1]=0
            g.accept(b'S,1,4294964100,4294964200', .01)
            r.record('task',{'grip_sample_id':samples[2]['record_id'],'task_use_host_s':.02})
            with self.assertRaises(RuntimeError):g.accept(b'0,1,1,4516', .02)
            r.close()
            model=export_session(r.directory,r.directory/'timing')
            self.assertEqual(model['status'],'offset_only')

    def test_long_gap_and_interval(self):
        for frame in [b'0,1,20,78125',b'0,1,1,99999']:
            with tempfile.TemporaryDirectory() as folder:
                r=Recorder(folder,{})
                g=GripReader(r,transport=FakeSerial([]),require_timing=True)
                g.accept(b'0,1,0,0',0)
                with self.assertRaises(RuntimeError):g.accept(frame,.01)
                r.close()

    def test_invalid_slot_advances_trial_without_physics(self):
        c=test_task.TaskTests().config();c['sample_block_size']=1
        c['durations']['pre_run']=c['durations']['prepare']=0
        t=Task(c,[],10000);t.tick(.81)
        before=(t.x,t.y,t.vy,t.feedback_steps)
        t.tick(None,valid=False)
        self.assertEqual((t.x,t.y,t.vy,t.feedback_steps),before)
        self.assertEqual(t.blocks,2)

    def test_clock_drift_and_no_evidence(self):
        exchanges=[dict(sync_id=i,net_rtt_s=.01,device_mid_s=i,host_mid_s=2+1.0001*i) for i in range(15)]
        model=fit_clock(exchanges)
        self.assertAlmostEqual(model['scale'],1.0001)
        self.assertEqual(fit_clock([])['status'],'unavailable')
