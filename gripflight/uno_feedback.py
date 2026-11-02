"""UNO calibration cue: live effort changes an orb, never a completion meter."""
import math
import time

from .gl_safety import set_text_layout


def feedback_scale(baseline, gain):
    # Fixed for all three attempts, based on ADC headroom, not a rolling personal max.
    return max(.05*abs(gain), .1*max(0,5*abs(gain)-baseline))


def orb_amount(raw, baseline, scale):
    if raw is None or baseline is None:
        return 0.0
    delta=max(0,abs(raw)-baseline)
    return delta/(delta+scale)  # Smooth asymptote: no reachable "full" target.


class OrbMotion:
    """Frame-rate independent growth; any release returns to base within 0.8 s."""
    release_s = .8
    rise_s = .12

    def __init__(self):
        self.value = 0.0
        self.last_time = None

    def update(self, target, now):
        target = min(1.0, max(0.0, target))
        dt = 0 if self.last_time is None else max(0, now-self.last_time)
        self.last_time = now
        if target >= self.value:
            self.value += (target-self.value)*(1-math.exp(-dt/self.rise_s))
        else:
            self.value = max(target, self.value-dt/self.release_s)
        return self.value


def phase_color(phase):
    if phase == 'zero' or phase.startswith('rest'):
        return (.48, .48, .48)
    return (.94, .22, .25) if phase.startswith('squeeze') else (.20, .80, .40)


class OrbFeedback:
    def __init__(self, display):
        from .calibration import settings
        import sys
        self.d=display;v=display.visual;w=display.win
        self.motion=OrbMotion()
        font=settings(display.config)['font']
        if font=='auto':font='PingFang SC' if sys.platform=='darwin' else 'Microsoft YaHei' if sys.platform=='win32' else 'Noto Sans CJK SC'
        self.title=v.TextStim(w,font=font,height=.05,pos=(0,.34),color='white',autoLog=False)
        self.detail=v.TextStim(w,font=font,height=.027,pos=(0,.24),color='#b6c8d6',autoLog=False)
        self.hint=v.TextStim(w,font=font,height=.025,pos=(0,-.31),color='#b6c8d6',autoLog=False)
        self.foot=v.TextStim(w,font=font,height=.022,pos=(0,-.43),color='#8495a8',autoLog=False)
        self.orb=v.Circle(w,radius=.06,edges=96,lineColor=None,fillColor='#46b5cc',autoLog=False)
        self.halo=v.Circle(w,radius=.07,edges=96,lineColor=None,fillColor='#46b5cc',opacity=.1,autoLog=False)
        self.shine=v.Circle(w,radius=.01,edges=48,lineColor=None,fillColor='white',opacity=.22,autoLog=False)
        self.labels=[v.TextStim(w,font=font,height=.025,color='#c6d9e6',autoLog=False) for _ in range(3)]

    def ball(self,x,y,r,amount,phase="complete"):
        color=phase_color(phase)
        self.orb.colorSpace=self.halo.colorSpace='rgb1'
        self.orb.fillColor=self.halo.fillColor=color
        for factor,opacity in ((1.23,.05),(1.12,.10)):
            self.halo.pos=(x,y);self.halo.radius=r*factor;self.halo.opacity=opacity;self.halo.draw()
        self.orb.pos=(x,y);self.orb.radius=r;self.orb.draw()
        self.shine.pos=(x-r*.28,y+r*.30);self.shine.radius=r*.16;self.shine.draw()

    def draw(self,title,detail,state):
        left,aspect=self.d.content_bounds();cx=left+aspect/2
        phase=state['phase'];baseline=state.get('baseline');scale=state.get('scale',1)
        size_scale=min(1,aspect/.9)
        resting=phase.startswith('rest')
        muted=resting or phase=='zero'
        if not phase.startswith('squeeze'):
            set_text_layout(self.title, height=.04 if resting else .05)
        self.title.color='#999999' if muted else 'white'
        self.detail.color='#999999' if muted else '#b6c8d6'
        self.hint.color='#999999' if muted else '#b6c8d6'
        self.title.pos=(cx,.34);self.detail.pos=(cx,.24)
        self.hint.pos=(cx,-.31);self.foot.pos=(cx,-.43)
        for text in (self.title,self.detail,self.hint,self.foot):
            set_text_layout(text, wrapWidth=aspect*.9)
        self.title.text=title;self.detail.text=detail
        if phase=='complete':
            self.detail.text='三次最大握力记录已保存'
            for i,peak in enumerate(state['peaks']):
                amount=orb_amount(peak,baseline,scale)
                x=cx+(i-1)*aspect*.28
                self.ball(x,-.015,(.035+.07*amount)*size_scale,amount)
                label=self.labels[i];label.pos=(x,-.20);label.text=f'第 {i+1} 次\n{peak:.3f}';label.draw()
            self.hint.text=''
            self.foot.text='按空格开始实验 · Esc 退出'
        else:
            squeezing=phase.startswith('squeeze')
            amount=orb_amount(state.get('raw'),baseline,scale) if squeezing else 0
            amount=self.motion.update(amount, state.get('host_s',time.monotonic()))
            if squeezing:
                # Quantized font sizes avoid rebuilding text for tiny frame-to-frame changes.
                set_text_layout(self.title, height=round((.05+.012*amount)*2000)/2000)
            radius=(.045+.13*amount)*size_scale
            self.ball(cx,-.035,radius,amount,phase)
            self.hint.text=('继续用最大力度握紧' if state.get('raw') is not None else '等待有效握力数据') if squeezing else ('松开并休息，等待下一次提示' if phase.startswith('rest') else '请保持放松，不要触碰传感器')
            self.foot.text='Esc 退出'
        self.title.draw();self.detail.draw();self.hint.draw();self.foot.draw()
