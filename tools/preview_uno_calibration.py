"""Render actual PsychoPy calibration stimuli using synthetic readings, no hardware."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from gripflight.display import Display
from gripflight.uno_feedback import feedback_scale
c=json.loads((ROOT/'config.json').read_text());c['display'].update(fullscreen=False,screen=0,size=[960,700],pos=[20,60])
out=Path(sys.argv[1]) if len(sys.argv)>1 else Path('/private/tmp/uno_orb_preview');out.mkdir(parents=True,exist_ok=True)
d=Display(c,ROOT,[])
try:
    for name,phase,raw,title,detail in [
        ('prepare','zero',None,'正在准备 请勿触碰','零点采集\n剩余 3.0 秒'),
        ('grip_low','squeeze_1',.85,'最大力度握紧','第 1 / 3 次'),
        ('grip_high','squeeze_1',1.6,'最大力度握紧','第 1 / 3 次'),
        ('rest','rest_1',None,'请松开握力器 休息','第 1 / 3 次\n剩余 14.0 秒'),
        ('complete','complete',None,'校准完成 请松开握力器','')]:
        d.uno_orb_feedback=dict(phase=phase,raw=raw,baseline=.8,scale=feedback_scale(.8,1),elapsed=2,peaks=[1.2,1.4,1.6])
        # Advance the real renderer's animation clock explicitly for reproducible synthetic previews.
        for frame in range(61):
            d.uno_orb_feedback['host_s']=getattr(d,'preview_time',0)+1/60
            d.preview_time=d.uno_orb_feedback['host_s']
            d.draw_calibration(title,detail,.5)
            if frame < 60: d.win.flip()
        d.win.getMovieFrame(buffer='back')
        d.win.movieFrames[-1].save(out/(name+'.png'))
        d.win.flip()
    print(out)
finally:d.close()
