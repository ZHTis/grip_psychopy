"""UNO single-channel protocol, scalar calibration and effort conversion."""
import math

from .base import ControlInput, InputDevice
from .uno_calibration import run_calibration
from ..calibration import settings, CalibrationAborted
from ..grip import GripReader
from ..ports import resolve_ports


def normalize(raw, minimum, maximum):
    """Original UNO mapping, now outside the game physics."""
    if not all(math.isfinite(v) for v in (raw, minimum, maximum)) or maximum <= minimum:
        raise ValueError('UNO raw value and calibration range must be finite and valid')
    return max(0.0, min(1.0, (abs(raw)-minimum)/(maximum-minimum)))


class UnoDevice(InputDevice):
    name = 'uno'
    default_config = 'config.json'
    completion_hold_s = 1
    extra_sources = ('gripflight/input_devices/uno.py', 'gripflight/input_devices/uno_calibration.py', 'gripflight/uno_monitor.py', 'gripflight/uno_feedback.py')

    def configure(self):
        c, args = self.config, self.args
        settings(c)
        gain = c['grip']['gain']
        if not math.isfinite(gain) or gain == 0:
            raise ValueError('grip.gain must be finite and nonzero')
        normalize(c['task']['grip_min'], c['task']['grip_min'], c['task']['grip_max'])
        overrides = {}
        for section, override in (('grip', args.grip_port), ('markers', args.marker_port)):
            if override is not None:
                if not override.strip():
                    raise ValueError(section+' port must not be empty')
                overrides[section] = override.strip()
        resolve_ports(c, overrides, simulate=args.simulate)
        if c['task']['sample_block_size'] != 1 or c['task']['sampling_rate'] != c['grip'].get('sample_rate', 256):
            raise ValueError('Ordered acquisition requires sample_block_size=1 and task sampling_rate=grip sample_rate')
        self.port = c['grip']['port']
        self.runtime = dict(control_clock='ordered device sample slots; invalid slots advance time without physics',
                            calibration_strategy='single-channel zero and three squeeze peaks')

    def create_display(self, objects):
        from ..display import Display
        if not getattr(self.args, 'no_grip_monitor', False):
            from ..uno_monitor import detect_layout
            layout = detect_layout(self.config['display'].get('screen',1), self.args.windowed)
            self.config['display'].update(layout)
            self.monitor_layout = layout
        return Display(self.config, self.root, objects)

    def start(self, recorder, devices, display):
        self.recorder, self.devices = recorder, devices
        self.monitor = None
        self.display = display
        self._escape_latched = False
        if display:
            display.abort_requested = lambda: self.stop_requested
        if display and hasattr(self, 'monitor_layout'):
            from ..uno_monitor import UnoMonitor
            self.monitor = UnoMonitor(self.monitor_layout['monitor_split'], check_abort=self._check_abort)
            display.calibration_observer = self._monitor_calibration
        try:
            self.reader = GripReader(recorder, simulate=self.args.simulate, ordered=True,
                **{k:v for k,v in self.config['grip'].items() if k != 'stale_timeout_s'})
            self.reader.start()
            devices.grip = self.reader
        except Exception as exc:
            devices.warning('grip_start', exc)

    def calibrate(self, display, setup):
        self._calibration_setup = setup
        run_calibration(display, self.reader, self.recorder, self.config, setup)
        self.devices.fallback_raw = self.config['task']['grip_min']

    def begin_task(self):
        if not self.args.headless:
            if self.reader is None:
                raise RuntimeError('Grip reader unavailable')
            self.reader.wait_ready(check_abort=self._check_abort)
            self.reader.begin_task()

    def convert(self, sample):
        t = self.config['task']
        valid = sample['valid']
        relative = ((abs(sample['raw'])-t['grip_min'])/(t['grip_max']-t['grip_min'])) if valid else None
        calibrated = bool(getattr(self, 'calibration_id', None))
        return ControlInput(
            metrics=dict(calibration_id=getattr(self, 'calibration_id', None), calibration_valid=calibrated,
                debug_mode=self.config.get('calibration', {}).get('debug_mode', False),
                absolute_value=abs(sample['raw']) if valid else None, absolute_unit='abs(voltage * gain)',
                baseline_value=t['grip_min'], calibration_range=t['grip_max']-t['grip_min'],
                relative_calibrated=relative if calibrated else None,
                percent_calibrated=100*relative if calibrated and relative is not None else None),
            normalized=normalize(sample['raw'], t['grip_min'], t['grip_max']) if valid else 0.0,
            raw=abs(sample['raw']) if valid else None, valid=valid, lift_gain=t['lift_gain'],
            sample_id=sample['record_id'], received_at=sample['t'],
            device_sequence=sample.get('device_sequence'), acquisition_id=sample.get('acquisition_id'))

    def read_inputs(self, now, keys, pressed):
        t = self.config['task']
        if self.args.simulate and self.reader:
            self.reader.simulated_voltage = (t['grip_max'] if pressed or 'space' in keys else t['grip_min'])/abs(self.config['grip']['gain'])
        samples = ([dict(raw=t['grip_min'], valid=True, record_id=None, t=None)]
                   if self.args.headless else self.reader.take_samples())
        return [self.convert(sample) for sample in samples]

    @property
    def stop_requested(self):
        monitor = getattr(self, 'monitor', None)
        return bool(getattr(self, '_escape_latched', False) or (monitor and monitor.abort.is_set()))

    def _check_abort(self):
        display = getattr(self, 'display', None)
        if display and 'escape' in display.event.getKeys():
            self._escape_latched = True
        if self.stop_requested:
            raise CalibrationAborted()

    def _monitor_calibration(self, stage):
        self._publish_monitor(stage)

    def _publish_monitor(self, stage):
        monitor = getattr(self, 'monitor', None)
        if monitor is None:
            return
        setup = getattr(self, '_calibration_setup', None)
        calibrated = bool(getattr(self, 'calibration_id', None)) or bool(
            setup and setup.data['calibration']['status'] == 'complete')
        t = self.config['task']
        reference = [t['grip_min'], t['grip_max']] if calibrated else None
        monitor.publish(self.reader, self.recorder.now(), stage, reference,
                        self.config.get('calibration', {}).get('debug_mode', False),
                        event_log=self.recorder.recent_events,
                        markers_enabled=self.config.get('markers', {}).get('enabled', True),
                        markers_simulated=self.config.get('runtime', {}).get('simulate',False))

    def present(self, task, display):
        labels = dict(pre_run='准备开始', prepare='准备', feedback='飞行任务',
                      result='结果', iti='轮间休息', complete='实验结束')
        self._publish_monitor(f"第 {task.trial} 轮 · {labels.get(task.phase,task.phase)}")

    def stop_controls(self):
        if getattr(self, 'monitor', None):
            self.monitor.close()
            self.monitor = None

    def save_setup(self, setup):
        t = self.config['task']
        setup.data['scalar_input'] = dict(minimum=t['grip_min'], maximum=t['grip_max'],
            lift_gain=t['lift_gain'], formula='clip((abs(raw)-minimum)/(maximum-minimum), 0, 1)')
        super().save_setup(setup)
