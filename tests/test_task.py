import copy
import json
from pathlib import Path
import unittest
from gripflight.task import Task, load_map

ROOT = Path(__file__).resolve().parents[1]


class TaskTests(unittest.TestCase):
    def config(self): return json.loads((ROOT/'config.json').read_text())['task']

    def test_original_timing_and_ten_trials(self):
        c = self.config()
        c.update(gravity=0, lift_gain=0, forward_speed=.01)
        t = Task(c, [], 10000)
        events = t.take_events()
        for _ in range(10000):
            t.tick(.81)
            events.extend(t.take_events())
            if t.phase == 'complete': break
        self.assertEqual(t.trial, 10)
        self.assertEqual(t.phase, 'complete')
        successes = [s for name, s in events if name == 'success']
        self.assertEqual(len(successes), 10)
        self.assertTrue(all(s['reason'] == 'duration' and s['feedback_steps'] == 360 for s in successes))
        starts = [s for n,s in events if n == 'trial_start']
        self.assertEqual(starts[0]['tick'], 8)
        self.assertEqual(starts[1]['tick']-starts[0]['tick'], 384)
        self.assertEqual([n for n,s in events][-2:], ['trial_end', 'run_end'])

    def test_collision_priority_and_boundary(self):
        c = self.config(); c['durations']['pre_run'] = c['durations']['prepare'] = 0
        c.update(player_start=[20,10], gravity=0, lift_gain=0)
        t = Task(c, [], 21)
        t.tick(.81); t.tick(.81)
        self.assertEqual(t.result, 2)
        self.assertEqual(t.reason, 'collision')

    def test_map_finish_and_physics(self):
        c = self.config(); c['durations']['pre_run'] = c['durations']['prepare'] = 0
        t = Task(c, [], 21)
        t.tick(.81); t.tick(1.20)
        self.assertAlmostEqual(t.x, 23.75)
        vy = (150-15)*.125*.98**7.5
        self.assertAlmostEqual(t.vy, vy)
        self.assertAlmostEqual(t.y, 50+vy*.125)
        self.assertEqual(t.reason, 'map_finish')

    def test_csv_original_finish_rule(self):
        objects, finish = load_map(ROOT/'maps/random.csv')
        self.assertEqual(finish, max(o['x']+o['width']/2 for o in objects)+50)
        self.assertEqual(objects[0]['type'], 'top')


if __name__ == '__main__': unittest.main()
