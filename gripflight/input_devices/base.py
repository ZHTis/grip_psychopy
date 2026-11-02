"""Device-to-game boundary: a normalized effort plus traceable acquisition metadata."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class ControlInput:
    # The game never interprets voltages, channel arrays or device calibration.
    normalized: float
    lift_gain: float
    raw: Optional[float] = None
    valid: bool = True
    sample_id: Optional[int] = None
    received_at: Optional[float] = None
    device_sequence: Optional[int] = None
    acquisition_id: Optional[str] = None
    reused: bool = False
    hand: Optional[str] = None
    weight_revision: Optional[int] = None
    metrics: dict = field(default_factory=dict)

    def record_fields(self, used_at):
        return dict(self.metrics, grip_sample_id=self.sample_id, grip_valid=self.valid,
                    grip_device_sequence=self.device_sequence,
                    grip_acquisition_id=self.acquisition_id, task_use_host_s=used_at,
                    grip_age_s=None if self.received_at is None else used_at-self.received_at,
                    input_reused=self.reused, input_hand=self.hand,
                    weight_revision=self.weight_revision, lift_gain=self.lift_gain)


class InputDevice:
    """Lifecycle owned by runner; sampling, calibration and UI owned by the device.

    read_inputs returns zero or more physics steps in order. A missing UNO sample
    is an invalid step, whereas an RX host tick can reuse a valid received frame.
    Neither behavior is inferred by the shared game loop.
    """
    strict_markers = False
    strict_recording = False
    completion_hold_s = 0
    extra_sources = ()

    def __init__(self, config, args, root):
        self.config, self.args, self.root = config, args, root
        self.reader = None

    @property
    def stop_requested(self):
        return False

    @property
    def acquisition_id(self):
        return self.reader.acquisition_id if self.reader else None

    def configure(self):
        raise NotImplementedError

    def create_display(self, objects):
        raise NotImplementedError

    def start(self, recorder, devices, display):
        raise NotImplementedError

    def calibrate(self, display, setup):
        raise NotImplementedError

    def begin_task(self):
        raise NotImplementedError

    def read_inputs(self, now, keys, pressed):
        raise NotImplementedError

    def present(self, task, display):
        """Publish optional device telemetry before the shared display draw."""

    def save_setup(self, setup):
        setup.data['device_input'] = dict(device=self.name, contract='normalized_effort_v1',
                                        control_clock=self.runtime['control_clock'])
        setup.save()

    def stop_controls(self):
        """Stop external edits before recording the final configuration."""

    def close(self):
        if self.reader:
            self.reader.close()
