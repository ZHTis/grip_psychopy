"""Hardware-free native-window stress check, including calibration and orderly Esc.
Output is explicitly simulated and is kept under exports, never real study data.
"""
import gc
import json
from pathlib import Path
import queue
import sys
import threading
import time
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def hidden_monitor_main(*arguments):
    # This function is imported in the spawned test child, not the production UI.
    from gripflight import uno_monitor
    make=uno_monitor.make_window
    def hidden_window(*a,**kw):
        window=make(*a,**kw)
        window.show=lambda:None
        return window
    uno_monitor.make_window=hidden_window
    uno_monitor.monitor_main(*arguments)


def main():
    from tests.test_input_devices import args
    from gripflight import runner
    from gripflight.display import Display
    from gripflight.calibration import CalibrationAborted
    if '--hidden' in sys.argv:
        from gripflight import uno_monitor
        uno_monitor.monitor_main=hidden_monitor_main
    from pyglet import gl
    from pyglet.image import Texture
    output=ROOT/'data_viewer/exports/gl_stress'
    output.mkdir(parents=True,exist_ok=True)
    config=json.loads((ROOT/'config.json').read_text())
    config['output']=str(output)
    config['task']['number_of_trials']=10000
    config_path=output/'simulated_config.json';config_path.write_text(json.dumps(config))
    options=args(str(config_path));options.no_grip_monitor=False
    native_delete=gl.glDeleteTextures
    failures=[];deletes=[];probe_count=[0];items=queue.Queue();stop=threading.Event()
    def checked_delete(*arguments):
        if threading.current_thread() is not threading.main_thread():
            failures.append('OpenGL texture deletion on worker thread')
            raise RuntimeError(failures[-1])
        deletes.append(time.perf_counter());return native_delete(*arguments)
    gl.glDeleteTextures=checked_delete
    def collect_worker():
        while not stop.is_set():
            try:
                texture=items.get(timeout=.02)
                del texture
            except queue.Empty:pass
            gc.collect()
    worker=threading.Thread(target=collect_worker,name='stress-background-gc')
    original_init=Display.__init__;original_draw=Display.draw;original_cal=Display.draw_calibration
    start=[None]
    def init(self,*a,**kw):
        original_init(self,*a,**kw);start[0]=time.perf_counter()
        if '--hidden' in sys.argv:
            self.win.waitBlanking=False
            self.win.winHandle.set_vsync(False)
            self.win.winHandle.set_visible(False)
            # Cocoa's event pump can wait indefinitely with every window hidden.
            # Exercise rendering/IPC here; visible/manual runs retain native input.
            self.win.winHandle.dispatch_events=lambda:None
            # PsychoPy also waits on an NSWindow display-link callback,
            # independently of vsync; hidden windows receive no such callback.
            backend=self.win.backend
            if hasattr(backend,'refreshEventHandlerMacOS'):
                self._hidden_display_link=backend.refreshEventHandlerMacOS
                del backend.refreshEventHandlerMacOS
        original_event=self.event
        def keys(*a,**kw):
            values=[] if '--hidden' in sys.argv else original_event.getKeys(*a,**kw)
            if time.perf_counter()-start[0]>95:return values+['escape']
            if getattr(self,'uno_orb_feedback',{}).get('phase')=='complete':return values+['space']
            return values
        self.event=SimpleNamespace(getKeys=keys,clearEvents=original_event.clearEvents)
        self.mouse=SimpleNamespace(getPressed=lambda:[getattr(self,'uno_orb_feedback',{}).get('phase','').startswith('squeeze'),False,False])
        worker.start()
    def probe():
        if probe_count[0]<200:
            items.put(Texture.create(4,4));probe_count[0]+=1
    def cal(self,*a,**kw):probe();return original_cal(self,*a,**kw)
    def draw(self,*a,**kw):probe();return original_draw(self,*a,**kw)
    Display.__init__=init;Display.draw_calibration=cal;Display.draw=draw
    def simulated_calibration(device,display,setup):
        device.config['calibration']['enabled']=True
        device.calibrate(display,setup)
        setup.data['calibration'].update(measured=False,simulated_test=True)
        setup.save()
    runner.prepare_calibration=simulated_calibration
    try:
        runner.run(options)
    finally:
        stop.set()
        if worker.ident is not None:worker.join(5)
        gl.glDeleteTextures=native_delete
    sessions=sorted(output.glob('20*/metadata.json'))
    metadata=json.loads(sessions[-1].read_text())
    setup=json.loads((sessions[-1].parent/'experiment_setup.json').read_text())
    result=dict(seconds=time.perf_counter()-start[0],native_delete_calls=len(deletes),
        worker_texture_probes=probe_count[0],worker_gl_failures=failures,
        session_status=metadata['status'],calibration_status=setup['calibration']['status'],
        session=str(sessions[-1].parent))
    (output/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result),flush=True)
    assert not failures and probe_count[0]==200
    assert metadata['status']=='aborted' and setup['calibration']['status']=='complete'


if __name__=='__main__':main()
