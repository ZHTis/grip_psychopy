import json
import queue
import tempfile
import unittest
from unittest.mock import Mock,patch
from gripflight.event_log import EventHistory,event_status,event_name
from gripflight.runtime import ContinuingRecorder,ContinuingDevices
from gripflight.markers import MarkerOutput
from gripflight.uno_monitor import UnoMonitor


class EventLogTests(unittest.TestCase):
    def test_local_events_have_same_timestamp_as_sqlite_and_never_ack(self):
        with tempfile.TemporaryDirectory() as root:
            r=ContinuingRecorder(root,{})
            devices=ContinuingDevices(r,.8,markers_enabled=False)
            eid=devices.send('trial_start',2)
            rows=r.recent_events()
            t,p=r.backend.db.execute('SELECT t,payload FROM records WHERE id=?',(eid,)).fetchone()
            self.assertEqual(rows[0]['t'],t)
            self.assertEqual(rows[0]['code'],json.loads(p)['code'])
            self.assertIn('打标关闭',event_status(rows[0]))
            self.assertEqual(event_name(rows[0]),'试次开始')
            self.assertEqual(len(rows),1)
            r.close('complete')

    def test_async_marker_ack_done_are_correlated_and_not_hardware_claims(self):
        with tempfile.TemporaryDirectory() as root:
            r=ContinuingRecorder(root,{})
            marker=MarkerOutput(r,{'feedback_start':3},simulate=True,mode='output_only',pulse_ms=1)
            eid=marker.send('feedback_start');marker.close()
            rows=r.recent_events()
            self.assertEqual([x['kind'] for x in rows],['marker_request','marker_ack','marker_done'])
            for row in rows:
                self.assertEqual(row['name'],'feedback_start');self.assertEqual(row['code'],3)
                self.assertIn('模拟',event_status(row))
            self.assertEqual(rows[1]['event_id'],eid)
            self.assertIn('无硬件输出',event_status(rows[2]))
            r.close('complete')

    def test_history_is_bounded_and_read_does_not_consume(self):
        h=EventHistory(capacity=3)
        for i in range(10):h.append('marker_request',dict(name='trial_start',code=2),i,i)
        self.assertEqual(len(h.rows),3);self.assertEqual(len(h.requests),3)
        a=h.snapshot();a[0]['name']='changed'
        self.assertEqual(h.snapshot()[0]['name'],'trial_start')
        self.assertEqual([r['index'] for r in h.snapshot()],[8,9,10])
        h.append('grip',{'raw':1},11,11);self.assertEqual(len(h.snapshot()),3)

    def test_failed_disk_write_is_not_shown_as_saved(self):
        with tempfile.TemporaryDirectory() as root:
            r=ContinuingRecorder(root,{})
            with patch.object(r.backend,'record',side_effect=OSError('disk full')):
                r.record('event',{'name':'calibration_zero_start'})
            self.assertIn('未保存到磁盘',event_status(r.recent_events()[0]))
            r.close('error')

    def test_queue_backpressure_resends_full_snapshot(self):
        m=UnoMonitor.__new__(UnoMonitor);m.last_update=-float('inf');m.process=Mock();m.process.is_alive.return_value=True
        m.frames=queue.Queue(maxsize=1);m.frames.put('old')
        h=EventHistory();h.append('marker_request',dict(name='trial_start',code=2,local_only=True),1,1)
        m.publish(None,1,'test',None,event_log=h.snapshot,markers_enabled=False)
        m.frames.get();m.last_update=-float('inf')
        m.publish(None,2,'test',None,event_log=h.snapshot,markers_enabled=False)
        frame=m.frames.get();self.assertEqual(frame['events'][0]['code'],2)
        self.assertFalse(frame['markers_enabled'])

    def test_failure_and_local_calibration_are_explicit(self):
        self.assertIn('回读不符',event_status(dict(kind='marker_ack',readback_matches_expected=False)))
        self.assertIn('打标错误',event_status(dict(kind='marker_error',error='ACK timeout')))
        row=dict(kind='event',name='calibration_squeeze_1_end',status='invalid',reason='data_timeout')
        self.assertEqual(event_name(row),'握紧1结束');self.assertIn('data_timeout',event_status(row))
