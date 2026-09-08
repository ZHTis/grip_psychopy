"""BCI2000 FeedbackTask.Process and GripFlightTask physics, independent of display."""
import csv
import math
from pathlib import Path


def load_map(path):
    with Path(path).open(encoding='utf-8-sig') as f:
        rows = csv.DictReader(line for line in f if line.strip() and not line.lstrip().startswith('#'))
        objects = []
        for row in rows:
            obj = {k: row[k].strip() for k in ('type', 'assetId')}
            obj.update({k: float(row[k]) for k in ('x', 'y', 'width', 'height')})
            if not all(math.isfinite(obj[k]) for k in ('x', 'y', 'width', 'height')):
                raise ValueError('Non-finite map coordinate')
            if obj['width'] <= 0 or obj['height'] <= 0:
                raise ValueError('Invalid obstacle dimensions')
            objects.append(obj)
    if not objects:
        raise ValueError('Empty map')
    return objects, max(o['x'] + o['width'] / 2 for o in objects) + 50


class Task:
    def __init__(self, config, objects, finish):
        self.c, self.objects, self.finish = config, objects, finish
        self.dt = config['sample_block_size'] / config['sampling_rate']
        self.durations = {p: int(config['durations'][p] / self.dt) for p in
                          ('pre_run', 'prepare', 'feedback', 'result', 'iti')}
        self.phase, self.game_phase, self.trial, self.blocks = 'pre_run', 0, 0, 0
        self.tick_index, self.result, self.collision = 0, 0, -1
        self.x, self.y = config['player_start']
        self.vy = self.smoothed = 0.0
        self.raw = self.normalized = 0.0
        self.reason = ''
        self.events = []
        self.feedback_steps = 0
        self.emit('run_start')

    def snapshot(self):
        return dict(trial=self.trial, block=1, phase=self.phase, game_phase=self.game_phase,
                    tick=self.tick_index, phase_blocks=self.blocks, x=self.x, y=self.y, vy=self.vy,
                    raw=self.raw, normalized=self.normalized, smoothed=self.smoothed,
                    result=self.result, collision_object=self.collision + 1,
                    reason=self.reason, feedback_steps=self.feedback_steps)

    def emit(self, name):
        self.events.append((name, self.snapshot()))

    def take_events(self):
        events, self.events = self.events, []
        return events

    def tick(self, raw):
        """One original source sample block, including same-block phase transitions."""
        if self.phase == 'complete':
            return
        while True:
            progress = self.blocks >= self.durations[self.phase]
            if self.phase == 'feedback':
                self.raw = abs(raw)
                self.normalized = max(0, min(1, (self.raw - self.c['grip_min']) /
                                            (self.c['grip_max'] - self.c['grip_min'])))
                self.smoothed += self.c['smoothing'] * (self.normalized - self.smoothed)
                self.x += self.c['forward_speed'] * self.dt
                self.vy += (self.c['lift_gain'] * self.smoothed - self.c['gravity']) * self.dt
                self.vy *= self.c['damping'] ** (self.dt * 60)
                self.y += self.vy * self.dt
                self.feedback_steps += 1
                w, h = self.c['player_size']
                outside = self.y - h / 2 <= 0 or self.y + h / 2 >= self.c['world_height']
                self.collision = -1
                if not outside:  # original short-circuit evaluation
                    for i, o in enumerate(self.objects):
                        if (abs(self.x-o['x']) <= (w+o['width'])/2 and
                                abs(self.y-o['y']) <= (h+o['height'])/2):
                            self.collision = i
                            break
                if outside or self.collision >= 0:
                    self.result, self.reason, self.game_phase = 2, 'collision', 3
                    progress = True
                elif self.x >= self.finish:
                    self.result, self.reason = 1, 'map_finish'
                    progress = True
            if not progress:
                break
            self.blocks = 0
            if self.phase in ('pre_run', 'iti'):
                self.trial += 1
                self.phase, self.game_phase = 'prepare', 1
                self.result, self.collision, self.reason = 0, -1, ''
                self.emit('trial_start')
            elif self.phase == 'prepare':
                self.phase, self.game_phase = 'feedback', 2
                self.x, self.y = self.c['player_start']
                self.vy = self.smoothed = 0.0
                self.feedback_steps = 0
                self.emit('feedback_start')
                break  # BCI2000: feedback lasts at least one sample block
            elif self.phase == 'feedback':
                if self.result == 0:
                    self.result, self.reason = 1, 'duration'
                self.phase = 'result'
                self.game_phase = 4 if self.result == 1 else 5
                self.emit('success' if self.result == 1 else 'collision')
            elif self.phase == 'result':
                self.game_phase = 6
                self.phase = 'iti'
                self.emit('trial_end')
                if self.trial >= self.c['number_of_trials']:
                    self.phase, self.game_phase = 'complete', 7
                    self.emit('run_end')
                    break
            else:
                raise RuntimeError(self.phase)
        self.blocks += 1
        self.tick_index += 1


def validate_config(c):
    t = c['task']
    for key in ('sample_block_size', 'sampling_rate', 'forward_speed', 'world_height'):
        if not math.isfinite(t[key]) or t[key] <= 0:
            raise ValueError(f'{key} must be positive')
    if type(t['number_of_trials']) is not int or t['number_of_trials'] < 1:
        raise ValueError('number_of_trials must be a positive integer')
    if not 0 <= t['smoothing'] <= 1 or not 0 <= t['damping'] <= 1:
        raise ValueError('smoothing/damping must be 0..1')
    if not t['grip_max'] > t['grip_min']:
        raise ValueError('grip_max must exceed grip_min')
    if t['gravity'] < 0 or t['lift_gain'] < 0:
        raise ValueError('gravity/lift_gain must be nonnegative')
    if len(t['player_size']) != 2 or min(t['player_size']) <= 0 or len(t['player_start']) != 2:
        raise ValueError('Invalid player size/start')
    if any(not math.isfinite(v) or v < 0 for v in t['durations'].values()):
        raise ValueError('Durations must be finite and nonnegative')
    for key in ('grip_min', 'grip_max', 'gravity', 'lift_gain', 'smoothing', 'damping'):
        if not math.isfinite(t[key]):
            raise ValueError(f'Non-finite {key}')
    required = {'run_start', 'trial_start', 'feedback_start', 'success', 'collision', 'trial_end', 'run_end', 'abort'}
    if not required <= c['markers']['codes'].keys():
        raise ValueError('Missing marker event codes')
