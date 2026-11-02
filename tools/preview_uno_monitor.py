import sys,math,os
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
os.environ['QT_QPA_PLATFORM']='offscreen'
from PyQt6.QtWidgets import QApplication
from gripflight.uno_monitor import make_window
from gripflight.event_log import EventHistory
app=QApplication([]);window=make_window();window.resize(670,850)
rows=[(i/256,.82+.48*max(0,math.sin(i/256*2))**3) for i in range(12*256)]
history=EventHistory()
for i,(t,name,code) in enumerate([(0.3,'run_start',1),(1.2,'trial_start',2),(2.2,'feedback_start',3),(5.9,'collision',5),(6.9,'trial_end',6),(8.2,'trial_start',2),(9.2,'feedback_start',3)],1):
    history.append('marker_request',dict(name=name,code=code,local_only=True,hardware_output_enabled=False),t,i)
window.apply_payload(dict(rows=rows,now=12,stage='第 2 轮 · 飞行任务（模拟示例）',reference=[.82,1.2],debug=False,events=history.snapshot(),markers_enabled=False))
window.show();app.processEvents()
output = Path(sys.argv[1]) if len(sys.argv)>1 else Path('/private/tmp/uno_curve_preview.png')
assert window.grab().save(str(output))
print(output)
window.close()
