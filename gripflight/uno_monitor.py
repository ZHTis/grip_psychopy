"""UNO observer UI in a separate Qt process; never consumes the task sample queue."""
import math
import multiprocessing
import queue
import time

from .event_log import event_name, event_status, event_color


def plan_layout(screens, primary=0, preferred=1, windowed=False):
    """Screen sizes and stimulus positions are logical pixels, not Retina framebuffer pixels."""
    primary = primary if 0 <= primary < len(screens) else 0
    others = [i for i in range(len(screens)) if i != primary]
    if others:
        target = preferred if preferred in others else others[0]
        w,h = screens[target]['width'], screens[target]['height']
        return dict(screen=target, fullscreen=not windowed,
                    size=[w,h] if not windowed else [int(w*.85),int(h*.8)],
                    pos=[0,0] if not windowed else [int(w*.075),int(h*.1)],
                    monitor_split=False, primary_screen=primary)
    w,h = screens[primary]['width'], screens[primary]['height']
    return dict(screen=primary, fullscreen=False, size=[int(w*.57)-24,h-110],
                pos=[12,60], monitor_split=True, primary_screen=primary)


def detect_layout(preferred=1, windowed=False):
    import pyglet
    platform = pyglet.canvas.get_display() if hasattr(pyglet, 'canvas') else pyglet.display.get_display()
    screens = platform.get_screens()
    default = platform.get_default_screen()
    primary = next((i for i,s in enumerate(screens) if s == default), 0)
    info = [dict(width=s.width,height=s.height,x=s.x,y=s.y) for s in screens]
    return dict(plan_layout(info,primary,preferred,windowed), detected_screens=info)


def series(rows, reference):
    absolute, relative = [], []
    for row in rows:
        t,raw = row[:2]
        voltage = row[2] if len(row)>2 else raw  # Legacy preview rows assumed gain=1.
        absolute.append((t,voltage))
        relative.append((t,100*(raw-reference[0])/(reference[1]-reference[0])
                         if raw is not None and reference else None))
    return absolute,relative


class UnoMonitor:
    def __init__(self, split, check_abort=None):
        ctx = multiprocessing.get_context('spawn')
        self.frames = ctx.Queue(maxsize=2)
        self.stop = ctx.Event()
        self.ready = ctx.Event()
        self.abort = ctx.Event()
        self.process = ctx.Process(target=monitor_main,args=(self.frames,self.stop,self.ready,self.abort,split),daemon=True)
        self.process.start()
        self.last_update = -math.inf
        try:
            deadline = time.perf_counter()+8
            while True:
                if check_abort:
                    check_abort()
                if self.abort.is_set():
                    from .calibration import CalibrationAborted
                    raise CalibrationAborted()
                if self.ready.wait(.02):
                    break
                if time.perf_counter() >= deadline or not self.process.is_alive():
                    raise RuntimeError('UNO curve window could not start')
        except BaseException:
            self.close()
            raise

    def publish(self, reader, now, stage, reference, debug=False, event_log=None, markers_enabled=True, markers_simulated=False):
        if time.perf_counter()-self.last_update < .1:
            return
        self.last_update = time.perf_counter()
        if not self.process.is_alive():
            return  # Closing the observer does not interrupt the experiment.
        rows = reader.monitor_history() if reader else []
        payload = dict(rows=rows, now=now, stage=stage, reference=reference, debug=debug,
                       error=str(reader.error) if reader and reader.error else None,
                       events=event_log() if callable(event_log) else (event_log or []),
                       markers_enabled=markers_enabled, markers_simulated=markers_simulated)
        try:
            self.frames.put_nowait(payload)
        except queue.Full:
            pass  # Visualization backpressure must never delay stimulus/serial processing.

    def close(self):
        self.stop.set()
        self.process.join(2)
        if self.process.is_alive():
            self.process.terminate(); self.process.join(1)
        self.frames.cancel_join_thread()
        self.frames.close()


def make_window(on_escape=None):
    from PyQt6.QtWidgets import QWidget, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView
    from PyQt6.QtCore import Qt, QRectF
    from PyQt6.QtGui import QPainter, QColor, QPen, QPainterPath, QFont, QShortcut, QKeySequence

    class CurveWindow(QWidget):
        def __init__(self):
            super().__init__()
            self.setWindowTitle('UNO · 握力曲线与打标日志')
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
            self.payload = dict(rows=[],now=0,reference=None,stage='等待设备',debug=False)
            self.resize(780,780)
            self.setMinimumSize(440,600)
            self.log_table=QTableWidget(0,4,self)
            self.log_table.setHorizontalHeaderLabels(['时间(s)','事件','码','状态'])
            self.log_table.verticalHeader().hide()
            self.log_table.verticalHeader().setDefaultSectionSize(25)
            self.log_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            self.log_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            self.log_table.setWordWrap(False)
            self.log_table.setStyleSheet('QTableWidget {background:#172231;color:#dbe5f0;gridline-color:#293647;border:1px solid #293647;font-size:12px;} QHeaderView::section {background:#243346;color:#cbd9e9;padding:4px;border:0;}')
            header=self.log_table.horizontalHeader()
            for col in (0,2):header.setSectionResizeMode(col,QHeaderView.ResizeMode.Fixed)
            for col in (1,3):header.setSectionResizeMode(col,QHeaderView.ResizeMode.Stretch)
            self.log_table.setColumnWidth(0,76);self.log_table.setColumnWidth(2,40)
            self._log_revision=None
            if on_escape:
                self.escape_shortcut=QShortcut(QKeySequence(Qt.Key.Key_Escape),self)
                self.escape_shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                self.escape_shortcut.activated.connect(on_escape)

        def log_top(self):
            return self.height()-max(175,min(245,int(self.height()*.30)))-40

        def resizeEvent(self,event):
            super().resizeEvent(event)
            if hasattr(self,'log_table'):
                top=self.log_top()
                self.log_table.setGeometry(16,top+30,self.width()-32,self.height()-top-68)

        def apply_payload(self,payload):
            self.payload=payload
            events=payload.get('events',[])
            revision=events[-1]['index'] if events else 0
            if revision!=self._log_revision:
                scroll=self.log_table.verticalScrollBar()
                at_bottom=scroll.value()>=scroll.maximum()-2
                previous=scroll.value()
                self.log_table.setRowCount(len(events))
                for i,row in enumerate(events):
                    values=(f"{row['t']:.3f}",event_name(row),str(row.get('code')) if row.get('code') is not None else '—',event_status(row))
                    tooltip=f"{row.get('name',row['kind'])} | {row['kind']} | event_id={row.get('event_id',row.get('record_id'))}\n{values[3]}"
                    for col,value in enumerate(values):
                        item=QTableWidgetItem(value);item.setForeground(QColor(event_color(row)));item.setToolTip(tooltip)
                        self.log_table.setItem(i,col,item)
                self._log_revision=revision
                if at_bottom:self.log_table.scrollToBottom()
                else:scroll.setValue(previous)
            self.update()

        def keyPressEvent(self, event):
            if event.key() == Qt.Key.Key_Escape and on_escape:
                on_escape()
                event.accept()
                return
            super().keyPressEvent(event)

        def paintEvent(self,event):
            p=QPainter(self);p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.fillRect(self.rect(),QColor('#111923'))
            p.setFont(QFont('Arial',12))
            def label(x,y,w,h,text,color='#dbe5f0'):
                p.setPen(QColor(color));p.drawText(QRectF(x,y,w,h),Qt.AlignmentFlag.AlignLeft|Qt.AlignmentFlag.AlignVCenter,text)
            d=self.payload;w=self.width();h=self.height()
            label(24,14,w-48,30,'UNO  实时握力  |  '+d['stage'])
            ref=d.get('reference')
            state=('已标定：零点 %.4f / 最大值 %.4f'%tuple(ref)) if ref else '尚未标定：实时显示 A0 电压'
            if d.get('debug'):state='DEBUG · '+state
            label(24,48,w-48,25,state,'#91a6be')
            absolute,relative=series(d['rows'],ref)
            now=d['now'];start=max(0,now-12);end=max(12,now)
            latest=next(((t,v) for t,v in reversed(absolute) if v is not None),None)
            stale=latest is None or now-latest[0]>.3
            a0_title = 'A0 电压（V） · 等待数据'
            if latest is not None:
                adc = round(latest[1]*1023/5)
                a0_title = f'A0：{latest[1]:.3f} V  |  ADC≈{adc}' + ('（旧值）' if stale else '')
            log_top=self.log_top()
            panel_h=(log_top-102)/2
            for idx,(points,title,color) in enumerate([(absolute,a0_title,'#4dd6b0'),(relative,'相对最大握力 | % 标定范围','#ffbf69')]):
                top=90+idx*(panel_h+12)
                visible=[v for t,v in points if v is not None and start<=t<=end]
                lo=min([0]+visible);hi=max(([100] if idx else [1])+visible)
                span=max(hi-lo,1e-6);lo-=span*.06;hi+=span*.12
                x,y,pw,ph=75,top+40,w-100,panel_h-80
                label(24,top,w-48,28,title,color)
                for tick in range(5):
                    val=lo+(hi-lo)*tick/4;yy=y+ph-ph*tick/4
                    p.setPen(QPen(QColor('#293647'),1));p.drawLine(int(x),int(yy),int(x+pw),int(yy))
                    label(8,yy-12,62,24,f'{val:.2f}' if idx==0 else f'{val:.0f}', '#91a6be')
                for seconds in (start,(start+end)/2,end):
                    xx=x+(seconds-start)/(end-start)*pw
                    label(min(w-75,max(0,xx-20)),y+ph+4,70,24,f'{seconds:.1f}s','#91a6be')
                if idx and not ref:
                    label(x+12,y+ph/2-15,pw-20,30,'完成最大握力标定后显示百分比','#91a6be')
                path=QPainterPath();connected=False;last_t=None
                for t,v in points:
                    if v is None or not start<=t<=end:
                        connected=False;continue
                    xx=x+(t-start)/(end-start)*pw;yy=y+ph-(v-lo)/(hi-lo)*ph
                    if not connected or (last_t is not None and t-last_t>.15):path.moveTo(xx,yy)
                    else:path.lineTo(xx,yy)
                    connected=True;last_t=t
                p.setPen(QPen(QColor(color),2));p.drawPath(path)
                for row in d.get('events',[]):
                    if row['kind']!='marker_request' or not start<=row['t']<=end:continue
                    xx=x+(row['t']-start)/(end-start)*pw
                    pen=QPen(QColor(event_color(row)),1);pen.setStyle(Qt.PenStyle.DashLine);p.setPen(pen)
                    p.drawLine(int(xx),int(y),int(xx),int(y+ph))
                    if row.get('code') is not None:label(xx+2,y+2,35,18,str(row['code']),event_color(row))
            mode=('模拟打标（不发硬件）' if d.get('markers_simulated') else '硬件打标已启用') if d.get('markers_enabled',True) else '仅本地（硬件关闭）'
            label(16,log_top,w-32,28,'打标 / 事件日志 · '+mode,'#b9a4ef')
            message=d.get('error') or ('等待新数据 / 数据已过期' if stale else '事件线为主机记录时间 · 非 TTL 实测时间')
            label(24,h-35,w-48,28,message,'#ffbf69' if stale or d.get('error') else '#91a6be')
            p.end()
    return CurveWindow()


def monitor_main(frames, stop, ready, abort, split):
    import os
    # Parent SVG rasterizer may set offscreen; this child must use the native window system.
    if os.environ.get('QT_QPA_PLATFORM') == 'offscreen':
        os.environ.pop('QT_QPA_PLATFORM')
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import QTimer
    app=QApplication([])
    window=make_window(on_escape=abort.set)
    area=app.primaryScreen().availableGeometry()
    if split:
        x=area.x()+int(area.width()*.59);y=area.y()+35
        window.setGeometry(x,y,int(area.width()*.40)-12,area.height()-70)
    else:
        window.setGeometry(area.x()+20,area.y()+35,min(900,area.width()-40),area.height()-70)
    def refresh():
        if stop.is_set():app.quit();return
        latest=None
        try:
            while True:latest=frames.get_nowait()
        except queue.Empty:pass
        if latest is not None:
            window.apply_payload(latest)
    timer=QTimer();timer.timeout.connect(refresh);timer.start(50)
    window.show();ready.set()
    app.exec()
