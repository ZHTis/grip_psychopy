"""RX device hand selection independent of the participant hand shown in the UI."""
import copy
import json
import math
import webbrowser

from .base import ControlInput, InputDevice
from .rx_calibration import calibrate
from ..calibration import settings
from ..multichannel import MultiChannelGripReader
from ..paths import project_path
from ..ports import resolve_ports
from ..weights import WeightModel, TickClock, evaluate
from ..weight_panel import PanelState, WeightPanel


def resolve_receiver(config, override=None, simulate=False):
    rx = config['multichannel']
    if override is not None:
        if not override.strip():
            raise ValueError('接收器串口不能为空')
        rx['port'] = override.strip()
    elif not simulate:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        identity = rx.get('serial_number')
        if identity:
            matches = [p.device for p in ports if p.serial_number == identity]
        elif rx.get('port'):
            matches = [rx['port']]
        else:
            matches = [p.device for p in ports if p.vid == 0x1a86]
        if len(matches) != 1:
            raise ValueError('无法唯一确定 RX-G0505M 接收器；用 --list-ports 查看，再用 --grip-port 指定')
        rx['port'] = matches[0]
    return rx.get('port')


class RXDevice(InputDevice):
    name = 'rx-g0505m'
    default_config = 'config_multichannel.json'
    strict_markers = True
    strict_recording = True
    extra_sources = ('assets/right_hand_map.svg', 'gripflight/input_devices/rx_g0505m.py',
                     'gripflight/input_devices/rx_calibration.py', 'gripflight/weights.py')

    def __init__(self, *args):
        super().__init__(*args)
        self.model = self.state = self.panel = None
        self.latest_sample = self.result = self.profile_now = None
        self.last_sample_id = None

    def configure(self):
        c, args = self.config, self.args
        rx = c['multichannel']
        self.source_hand = rx.get('hand')
        self.display_hand = rx.get('display_hand', 'right')
        if self.source_hand not in ('left', 'right'):
            raise ValueError('multichannel.hand must be the device protocol hand: left or right')
        if self.display_hand != 'right':
            raise ValueError('当前界面为右手测试，请使用 multichannel.display_hand=right')
        for key in ('stale_timeout_s', 'control_rate_hz'):
            if not isinstance(rx[key], (int,float)) or not math.isfinite(rx[key]) or rx[key] <= 0:
                raise ValueError('multichannel.'+key+' must be finite and positive')
        if rx['control_rate_hz'] > 1000:
            raise ValueError('control_rate_hz must not exceed 1000')
        self.profile_path = project_path(args.weights or rx.get('weights_file', 'right_hand_weights.json'))
        self.profile = json.loads(self.profile_path.read_text(encoding='utf-8-sig'))
        cs = settings(c)
        if cs['lift_mode'] == 'target_fraction':
            self.profile['lift_gain'] = c['task']['gravity']/cs['target_fraction']
        if self.profile.get('hand') != self.display_hand:
            raise ValueError('Weight profile must be for the right hand')
        self.port = resolve_receiver(c, args.grip_port, args.simulate)
        marker_config = copy.deepcopy(c)
        marker_config['grip'] = {'port': self.port or 'RX_SIMULATION'}
        marker_config.setdefault('serial_devices', {}).pop('grip', None)
        resolve_ports(marker_config, {'markers':args.marker_port} if args.marker_port is not None else {}, simulate=args.simulate)
        c['markers'] = marker_config['markers']
        c['task'].update(grip_min=0.0, grip_max=1.0, sampling_rate=rx['control_rate_hz'],
                         sample_block_size=1, lift_gain=self.profile['lift_gain'])
        self.runtime = dict(control_clock=f'fixed host ticks; zero-order hold of latest {self.source_hand} device frame, repeated use explicitly recorded',
            source_hand=self.source_hand, display_hand=self.display_hand,
            calibration_strategy='per-channel zero and three squeeze peaks', weight_profile_path=str(self.profile_path))

    def create_display(self, objects):
        from ..pressure_display import WeightedDisplay
        return WeightedDisplay(self.config, self.root, objects)

    def start(self, recorder, devices, display):
        self.recorder = recorder
        self.model = WeightModel(self.profile, recorder.record, self.profile_path)
        self.state = PanelState(self.model, recorder.record)
        self.state.simulated = self.args.simulate
        if not self.args.no_weight_panel and not self.args.headless:
            self.panel = WeightPanel(self.state)
            print('权重面板:', self.panel.url, flush=True)
            webbrowser.open(self.panel.url, new=1)
        self.reader = MultiChannelGripReader(recorder, port=self.port, simulate=self.args.simulate,
                                             simulated_hands=(self.source_hand,), ordered=True)
        self.reader.start()
        self.reader.wait_ready(timeout=5, hand=self.source_hand)
        if display:
            display.set_pressure(self.reader.latest(self.source_hand)['values_g'])

    def calibrate(self, display, setup):
        calibrate(display, self.reader, self.model, self.state, self.recorder, self.config, setup)

    def begin_task(self):
        self.reader.take_samples()
        self.clock = TickClock(self.config['multichannel']['control_rate_hz'])

    @property
    def stop_requested(self):
        return self.state is not None and self.state.stop

    def read_inputs(self, now, keys, pressed):
        if self.recorder.dropped_records:
            raise RuntimeError('记录保存失败，停止加权任务')
        if self.args.simulate:
            level = 1.0 if pressed else self.state.simulate_level
            self.reader.simulated_values_g = [round(level*(500+(i*79)%1500)) for i in range(25)]
        self.reader.take_samples()  # All protocol hands are recorded; only the configured device hand drives the game.
        sample = self.reader.latest(self.source_hand, max_age=self.config['multichannel']['stale_timeout_s'])
        profile = self.model.snapshot()
        result = evaluate(sample['values_g'], profile)
        self.latest_sample, self.profile_now, self.result = sample, profile, result
        count, stalled = (1,False) if self.args.headless else self.clock.advance(now, paused=self.state.paused)
        if stalled:
            self.recorder.record('diagnostic', dict(category='game_clock_stall', error='Game clock rescheduled after long host stall'))
        inputs = []
        for _ in range(count):
            inputs.append(ControlInput(normalized=result['normalized'], raw=result['weighted_g'],
                lift_gain=profile['lift_gain'], sample_id=sample['record_id'], received_at=sample['t'],
                acquisition_id=self.reader.acquisition_id, reused=self.last_sample_id==sample['record_id'],
                hand=sample['hand'], weight_revision=profile['revision'],
                metrics=dict(weighted_g=result['weighted_g'], reference_g=result['reference_g'], display_hand=self.display_hand,
                    calibration_id=getattr(self, 'calibration_id', None), calibration_valid=profile['calibrated'],
                    debug_mode=self.config.get('calibration', {}).get('debug_mode', False),
                    absolute_value=result['absolute_weighted_g'], absolute_unit='device-reported g (weighted mean)',
                    calibration_range=result['calibration_reference_g'],
                    relative_calibrated=result['relative_calibrated'], percent_calibrated=result['percent_calibrated'],
                    channel_values_g=sample['values_g'], channel_relative_calibrated=result['channel_relative_calibrated'],
                    **{f'point_{i:02d}_g': v for i,v in enumerate(sample['values_g'],1)},
                    **{f'point_{i:02d}_relative': v for i,v in enumerate(result['channel_relative_calibrated'],1)})))
            self.last_sample_id = sample['record_id']
        return inputs

    def present(self, task, display):
        # Also update controls/pressure while paused or between physics ticks.
        task.c['lift_gain'] = self.profile_now['lift_gain']
        message = ('游戏已暂停 · 数据持续采集' if self.state.paused else
                   f'第 {task.trial}/{task.c["number_of_trials"]} 次 · {task.phase}')
        self.state.publish(stage=task.phase, message=message, values_g=self.latest_sample['values_g'], fresh=True,
            result=self.result, gravity=task.c['gravity'], applied_lift=task.c['lift_gain']*task.smoothed,
            applied_revision=self.profile_now['revision'], simulated=self.args.simulate)
        if display:
            display.set_pressure(self.latest_sample['values_g'])

    def save_setup(self, setup):
        setup.data['hand_assignment'] = dict(source_hand=self.source_hand, display_hand=self.display_hand,
            note='Source is the device protocol identity; display is the participant test hand. Channel IDs are unchanged.')
        if self.model:
            snapshot = self.model.snapshot()
            self.config['task']['lift_gain'] = snapshot['lift_gain']
            setup.data['weighted_input'] = snapshot
        super().save_setup(setup)

    def stop_controls(self):
        if self.panel:
            self.panel.close()
