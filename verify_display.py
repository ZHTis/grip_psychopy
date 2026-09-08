"""Short visual smoke test using the actual PsychoPy runtime; saves QA screenshots."""
import json
from pathlib import Path
from gripflight.display import Display
from gripflight.task import Task, load_map

root = Path(__file__).parent
c = json.loads((root/'config.json').read_text())
objects, finish = load_map(root/c['map'])
t = Task(c['task'], objects, finish)
display = Display(c, root, objects)
try:
    (root/'verification').mkdir(exist_ok=True)
    for phase in ('prepare', 'feedback', 'result'):
        t.phase = phase
        t.x, t.y, t.result = 100, 45, 2
        display.draw(t)
        display.win.getMovieFrame(buffer='back')
        display.win.saveMovieFrames(str(root/'verification'/f'{phase}.png'))
        display.win.flip()
finally:
    display.close()
print('PsychoPy rendering completed')
