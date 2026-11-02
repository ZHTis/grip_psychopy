import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from gripflight.display import Display
from gripflight.pressure_display import WeightedDisplay, POSITIONS, map_layout, pressure_color

ROOT=Path(__file__).resolve().parents[1]


class Stim:
    def __init__(self):self.text='';self.draws=0
    def draw(self):self.draws+=1


class PressureDisplayTests(unittest.TestCase):
    def display(self,size=(1200,700)):
        d=WeightedDisplay.__new__(WeightedDisplay)
        d.win=SimpleNamespace(size=size);d.panel_fraction=.38;d.pressure_max_g=5000
        d.values=None;d._panel_size=None
        for key in ('panel_bg','hand','panel_title','panel_note','panel_footer'):setattr(d,key,Stim())
        d.sensors=[(Stim(),Stim(),Stim()) for _ in range(25)]
        return d

    def test_protocol_order_matches_hand_anatomy(self):
        self.assertEqual(len(set(POSITIONS)),25)
        self.assertEqual([POSITIONS[i-1] for i in (1,6,11)],[(32,310),(96,354),(158,400)])
        self.assertEqual([POSITIONS[i-1] for i in (2,7,12,17)],[(142,80),(158,150),(181,221),(202,292)])
        self.assertEqual([POSITIONS[i-1] for i in (16,21,22,23,24,25)],
                         [(206,430),(235,404),(209,354),(290,444),(336,434),(347,374)])

    def test_raw_value_updates_correct_point_and_color_clamps_only(self):
        d=self.display();values=[0]*25;values[0]=1453;values[5]=893;values[24]=65535
        d.set_pressure(values);d.draw_pressure()
        self.assertEqual(d.sensors[0][2].text,'1453')
        self.assertEqual(d.sensors[5][2].text,'893')
        self.assertEqual(d.sensors[24][2].text,'65535')
        self.assertEqual(d.sensors[24][0].fillColor,pressure_color(5000,5000))
        self.assertNotEqual(d.sensors[0][0].fillColor,d.sensors[1][0].fillColor)
        values[0]=0;self.assertEqual(d.values[0],1453)
        self.assertIn('65535',d.panel_note.text)
        for bad in ([0]*24,[float('nan')]+[0]*24,[-1]+[0]*24):
            with self.assertRaises(ValueError):d.set_pressure(bad)

    def test_all_points_fit_right_sidebar_across_aspects_and_retina(self):
        for size in ((1200,700),(2400,1400),(1920,1080),(1024,768),(800,900)):
            d=self.display(size);d.draw_pressure()
            aspect=size[0]/size[1]
            game_left,game_width=d.content_bounds();split=game_left+game_width
            for box,_,_ in d.sensors:
                x,y=box.pos;w,h=box.size
                self.assertGreaterEqual(x-w/2,split)
                self.assertLessEqual(x+w/2,aspect/2)
                self.assertGreater(y-h/2,-.43)
                self.assertLess(y+h/2,.38)
            self.assertAlmostEqual(d.panel_bg.pos[0]-d.panel_bg.size[0]/2,split)
        self.assertEqual(map_layout(1200/700,.38),map_layout(2400/1400,.38))

    def test_legacy_content_remains_full_width(self):
        d=Display.__new__(Display);d.win=SimpleNamespace(size=(1200,700))
        left,width=d.content_bounds()
        self.assertAlmostEqual(left,-1200/700/2)
        self.assertAlmostEqual(width,1200/700)
        self.assertAlmostEqual(left+width/2,0)

    def test_display_can_resize_and_show_waiting_without_fake_zero(self):
        d=self.display();d.draw_pressure()
        self.assertEqual(d.panel_note.text,'等待右手数据')
        before=d.sensors[0][0].pos
        d.win.size=(1920,1080);d.draw_pressure()
        self.assertNotEqual(d.sensors[0][0].pos,before)
        self.assertEqual(d.sensors[0][0].draws,2)

    def test_only_rx_rest_duration_is_six_seconds(self):
        old=json.loads((ROOT/'config.json').read_text())
        new=json.loads((ROOT/'config_multichannel.json').read_text())
        self.assertEqual(old['calibration']['rest_s'],15)
        self.assertEqual(new['calibration']['rest_s'],6)
        self.assertFalse(new['calibration']['enabled'])
        self.assertEqual(new['multichannel']['hand'],'left')
        self.assertEqual(new['multichannel']['weights_file'],'right_hand_weights.json')
        self.assertEqual(new['multichannel']['display_hand'],'right')
        self.assertTrue(old['calibration']['enabled'])
        self.assertEqual(new['calibration']['zero_s'],5)
        self.assertEqual(new['calibration']['squeeze_s'],1)
        self.assertEqual(new['calibration']['min_samples'],5)


if __name__=='__main__':unittest.main()
