"""RX-only PsychoPy sidebar using handy's mirrored right-palm map and channel order.

No serial access here: all values come from the task's existing reader.
Coordinates and SVG outline follow handy/index.html (manual page 6, section 2.5).
"""
import colorsys
import math
import sys

from .display import Display, rasterize

# Index 0 is protocol channel 1. Mirror x for the right palm, never channel IDs.
POSITIONS = tuple((450-x, y) for x, y in (
    (418,310),(308,80),(223,38),(134,68),(33,140),
    (354,354),(292,150),(215,108),(134,128),(45,196),
    (292,400),(269,221),(204,194),(138,198),(64,250),
    (244,430),(248,292),(194,276),(138,287),(95,310),
    (215,404),(241,354),(160,444),(114,434),(103,374),
))


def pressure_color(value, maximum):
    """Same HSL ramp as handy, returned as PsychoPy rgb255."""
    t = max(0.0, min(1.0, value/maximum))
    rgb = colorsys.hls_to_rgb((210-t*55)/360, (15+t*23)/100, (25+t*35)/100)
    return tuple(round(c*255) for c in rgb)


def map_layout(aspect, fraction):
    """Fit the entire 450x570 map inside the sidebar in height units."""
    width = aspect*fraction
    center = aspect/2-width/2
    scale = min((width-.04)/450, .76/570)
    return center, scale


class WeightedDisplay(Display):
    def __init__(self, config, root, objects):
        d = config['display']
        self.panel_fraction = d.get('pressure_panel_fraction', .38)
        self.pressure_max_g = d.get('pressure_color_max_g', 5000)
        if (type(self.panel_fraction) not in (int,float) or not .25 <= self.panel_fraction <= .6):
            raise ValueError('display.pressure_panel_fraction must be in 0.25..0.6')
        if (type(self.pressure_max_g) not in (int,float) or not math.isfinite(self.pressure_max_g)
                or self.pressure_max_g <= 0):
            raise ValueError('display.pressure_color_max_g must be finite and positive')
        super().__init__(config, root, objects)
        try:
            v = self.visual
            font = config.get('calibration', {}).get('font','auto')
            if font == 'auto':
                font = 'PingFang SC' if sys.platform == 'darwin' else (
                    'Microsoft YaHei' if sys.platform == 'win32' else 'Noto Sans CJK SC')
            self.panel_bg = v.Rect(self.win, fillColor='#19212d', lineColor=None, autoLog=False)
            self.hand = v.ImageStim(self.win, image=str(rasterize(root/'assets/right_hand_map.svg', root/'cache')), autoLog=False)
            self.panel_title = v.TextStim(self.win, text='右手 · 25 点实时压力', font=font,
                color='#e4edf5', height=.028, autoLog=False)
            self.panel_note = v.TextStim(self.win, text='', font=font,
                color='#a7b6c6', height=.019, autoLog=False)
            self.panel_footer = v.TextStim(self.win,
                text=f'上方通道 · 下方原始值 (g)\n颜色上限 {self.pressure_max_g:g} g · 仅影响显示',
                font=font, color='#a7b6c6', height=.017, autoLog=False)
            self.sensors = []
            for i in range(25):
                box = v.Rect(self.win, fillColor=pressure_color(0,self.pressure_max_g),
                    lineColor=(109,146,155), colorSpace='rgb255', lineWidth=1, autoLog=False)
                number = v.TextStim(self.win, text=f'{i+1:02d}', font='Arial',
                    color='#b8d2d7', autoLog=False)
                value = v.TextStim(self.win, text='—', font='Arial',
                    color='white', autoLog=False)
                self.sensors.append((box,number,value))
            self.values = None
            self._panel_size = None
        except BaseException:
            self.close()
            raise

    def content_bounds(self):
        aspect = self.win.size[0]/self.win.size[1]
        return -aspect/2, aspect*(1-self.panel_fraction)

    def set_pressure(self, values):
        if len(values) != 25 or any(not math.isfinite(x) or x < 0 for x in values):
            raise ValueError('Pressure display requires 25 finite nonnegative values')
        for i, value in enumerate(values):
            if self.values is None or value != self.values[i]:
                box, _, label = self.sensors[i]
                box.fillColor = pressure_color(value,self.pressure_max_g)
                label.text = f'{value:g}'
        self.values = tuple(values)

    def draw_pressure(self):
        size = tuple(self.win.size)
        if size != self._panel_size:
            aspect = size[0]/size[1]
            center, scale = map_layout(aspect,self.panel_fraction)
            self.panel_bg.pos = (center,0)
            self.panel_bg.size = (aspect*self.panel_fraction,1)
            self.panel_title.pos = (center,.445)
            self.panel_title.wrapWidth = aspect*self.panel_fraction*.94
            self.panel_note.pos = (center,.397)
            map_y = -.025
            self.hand.pos = (center,map_y)
            self.hand.size = (450*scale,570*scale)
            for (px,py),(box,number,value) in zip(POSITIONS,self.sensors):
                x,y = center+(px-225)*scale, map_y+(285-py)*scale
                box.pos,box.size = (x,y),(38*scale,26*scale)
                number.pos,number.height = (x,y+6*scale),9*scale
                value.pos,value.height = (x,y-6*scale),11*scale
            self.panel_footer.pos = (center,-.455)
            self.panel_footer.wrapWidth = aspect*self.panel_fraction*.94
            self._panel_size = size
        note = '等待右手数据' if self.values is None else f'掌面朝向你 · 最大单点 {max(self.values):g} g'
        if self.panel_note.text != note:
            self.panel_note.text = note
        # Opaque sidebar covers world objects crossing the game's right boundary.
        self.panel_bg.draw()
        self.panel_title.draw()
        self.panel_note.draw()
        self.hand.draw()
        for box,number,value in self.sensors:
            box.draw();number.draw();value.draw()
        self.panel_footer.draw()

    def draw(self, task):
        camera = super().draw(task)
        self.draw_pressure()
        return camera

    def draw_calibration(self, title, detail, progress):
        super().draw_calibration(title,detail,progress)
        self.draw_pressure()
