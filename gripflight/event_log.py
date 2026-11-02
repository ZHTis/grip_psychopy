"""Bounded observer copy of recorded events; never read SQLite from the UI."""
from collections import deque, OrderedDict
import threading

WATCHED = frozenset(('marker_request','marker_ack','marker_done','marker_error','event','diagnostic'))
FIELDS = ('name','code','event_id','mode','simulated','local_only','output_available',
          'hardware_output_enabled','status','reason','error','category','state',
          'readback_matches_expected','a0_matches_expected')


class EventHistory:
    def __init__(self, capacity=300):
        self.rows=deque(maxlen=capacity)
        self.requests=OrderedDict()
        self.lock=threading.Lock()
        self.revision=0

    def append(self, kind, payload, t, record_id):
        if kind not in WATCHED:
            return
        row={key:payload[key] for key in FIELDS if key in payload}
        row.update(kind=kind,t=t,record_id=record_id,saved=record_id is not None)
        with self.lock:
            self.revision+=1
            row['index']=self.revision
            if kind=='marker_request' and record_id is not None:
                self.requests[record_id]=(row.get('name','marker'),row.get('code'))
                while len(self.requests)>self.rows.maxlen:self.requests.popitem(last=False)
            elif kind.startswith('marker_'):
                request=self.requests.get(row.get('event_id'))
                if request:
                    row.setdefault('name',request[0]);row.setdefault('code',request[1])
            self.rows.append(row)

    def snapshot(self):
        with self.lock:
            return [dict(row) for row in self.rows]


def event_name(row):
    name=row.get('name') or row.get('category') or row['kind']
    names={'run_start':'实验开始','trial_start':'试次开始','feedback_start':'飞行开始',
           'success':'成功','collision':'碰撞','trial_end':'试次结束','run_end':'实验结束',
           'abort':'中止','calibration_complete':'标定完成','calibration_reference_ready':'标定值就绪',
           'calibration_zero_start':'零点采集开始','calibration_zero_end':'零点采集结束'}
    if name.startswith('calibration_'):
        parts=name.split('_')
        if len(parts)==4 and parts[1] in ('squeeze','rest'):
            return ('握紧' if parts[1]=='squeeze' else '休息')+parts[2]+('开始' if parts[3]=='start' else '结束')
    return names.get(name,name)


def event_status(row):
    kind=row['kind']
    if kind=='marker_request':
        if row.get('local_only') or row.get('hardware_output_enabled') is False:
            status='本地记录 · 打标关闭'
        elif row.get('output_available') is False:status='未发送 · 硬件不可用'
        elif row.get('simulated'):status='模拟请求'
        else:status='请求已记录 · 等待 ACK'
    elif kind in ('marker_ack','marker_done'):
        status=('模拟 ' if row.get('simulated') else '')+('ACK' if kind=='marker_ack' else 'DONE')
        if row.get('readback_matches_expected') is False or row.get('a0_matches_expected') is False:
            status+=' · 回读不符'
        elif row.get('simulated'):status+=' · 无硬件输出'
        elif row.get('mode')=='output_only':status+=' · 固件确认，无回读'
        elif row.get('readback_matches_expected') is True or row.get('a0_matches_expected') is True:
            status+=' · 回读匹配'
    elif kind=='marker_error':status='打标错误 · '+str(row.get('error','未知'))
    elif kind=='diagnostic':status=str(row.get('error') or row.get('state') or '诊断')
    else:
        status='本地事件'
        if row.get('status'):status+=' · '+str(row['status'])
        if row.get('reason'):status+=' · '+str(row['reason'])
    if not row.get('saved',True):status+=' · 未保存到磁盘'
    return status


def event_color(row):
    if row['kind'] in ('marker_error','diagnostic') or row.get('status')=='invalid' or row.get('readback_matches_expected') is False or row.get('a0_matches_expected') is False or not row.get('saved',True):
        return '#ff8585'
    if row.get('local_only') or row['kind']=='event':return '#b9a4ef'
    if row['kind'] in ('marker_ack','marker_done'):return '#4dd6b0'
    return '#ffbf69'
