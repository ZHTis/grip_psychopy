"""Compatibility entry point; RX and UNO now use the same session runner."""
from .input_devices.rx_calibration import calibrate, save_setup
from .input_devices.rx_g0505m import resolve_receiver


def run(args):
    from .runner import run as run_session
    return run_session(args, device_name='rx-g0505m')
