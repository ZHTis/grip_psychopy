"""PsychoPy rendering; original SVG files rasterized without redesign."""
import hashlib
from pathlib import Path

_qt_app = None


def rasterize(path, cache):
    path = Path(path)
    if path.suffix.lower() != '.svg':
        return path
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = Path(cache)
    cache.mkdir(parents=True, exist_ok=True)
    output = cache / (digest + '.png')
    if not output.exists():
        # Qt SVG is also the renderer used by BCI2000. PsychoPy Standalone
        # already includes PyQt6, so no separate SVG runtime is required.
        import os
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QGuiApplication, QImage, QPainter
        from PyQt6.QtSvg import QSvgRenderer
        global _qt_app
        _qt_app = QGuiApplication.instance() or QGuiApplication([])
        renderer = QSvgRenderer(str(path))
        if not renderer.isValid():
            raise ValueError(f'Invalid SVG: {path}')
        size = renderer.defaultSize() * 3
        image = QImage(size, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        if not image.save(str(output)):
            raise IOError(f'Could not rasterize {path}')
    return output


class Display:
    def __init__(self, config, root, objects):
        from psychopy import visual, event
        self.visual, self.event, self.config = visual, event, config
        d = config['display']
        self.win = visual.Window(size=d['size'], fullscr=d['fullscreen'], screen=d['screen'],
                                 units='pix', color='black', allowGUI=True, waitBlanking=True)
        try:
            self.background = visual.ImageStim(self.win, image=str(rasterize(root/config['assets']['background'], root/'cache')),
                                               size=self.win.size, autoLog=False)
            self.player = visual.ImageStim(self.win, image=str(rasterize(root/config['assets']['player'], root/'cache')), autoLog=False)
            self.obstacles = [(o, visual.Rect(self.win, fillColor='gray', lineColor='gray', autoLog=False)) for o in objects]
            self.text = visual.TextStim(self.win, color='white', height=self.win.size[1] * .12, autoLog=False)
            self.mouse = event.Mouse(win=self.win)
            from PIL import Image
            with Image.open(rasterize(root/config['assets']['player'], root/'cache')) as im:
                self.player_ratio = im.width / im.height
        except BaseException:
            self.win.close()
            raise

    def draw(self, task):
        ww, wh = self.win.size
        height = task.c['world_height']
        scale = wh / height
        camera = max(0, task.x - (height * ww / wh) * .30)
        if task.phase in ('feedback', 'result'):
            self.background.draw()
            for o, stim in self.obstacles:
                stim.pos = ((o['x'] - camera)*scale - ww/2, o['y']*scale - wh/2)
                stim.size = (o['width']*scale, o['height']*scale)
                if abs(stim.pos[0]) <= ww/2 + stim.size[0]/2:
                    stim.draw()
            self.player.pos = ((task.x-camera)*scale-ww/2, task.y*scale-wh/2)
            # BCI2000 AdjustWidth: aspect ratio follows image, collision box stays PlayerSize.
            bird_height = task.c['player_size'][1]*scale
            self.player.size = (bird_height*self.player_ratio, bird_height)
            self.player.draw()
        message = {'pre_run': 'Ready', 'prepare': 'Prepare', 'feedback': '',
                   'result': 'Complete' if task.result == 1 else 'Collision',
                   'iti': 'Complete' if task.result == 1 else 'Collision', 'complete': 'Run complete'}[task.phase]
        if message:
            self.text.text = message
            self.text.draw()
        return camera

    def close(self):
        self.win.close()
