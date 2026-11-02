"""Run from PsychoPy Coder or: python run_task.py --simulate."""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=None, help='Path relative to project root')
    parser.add_argument('--grip-port', help='Override grip port, e.g. COM6 or /dev/cu.usbmodem1301')
    parser.add_argument('--marker-port', help='Override marker port, e.g. COM10 or /dev/cu.usbmodem1401')
    parser.add_argument('--list-ports', action='store_true', help='List serial ports and exit without starting a session')
    parser.add_argument('--simulate', action='store_true', help='No hardware; mouse left/space gives full grip')
    parser.add_argument('--debug', action='store_true', help='Skip calibration; label recordings as debug, not measured MVC')
    parser.add_argument('--calibration-file', help='Reuse a saved calibration_profile.json for this participant and device')
    marker_switch = parser.add_mutually_exclusive_group()
    marker_switch.add_argument('--no-markers', dest='markers_enabled', action='store_false', help='Real grip input, local events only; no marker board needed')
    marker_switch.add_argument('--enable-markers', dest='markers_enabled', action='store_true', help='Enable hardware marker output')
    parser.set_defaults(markers_enabled=None)
    parser.add_argument('--headless', action='store_true', help='Fast logic smoke test, requires --simulate')
    parser.add_argument('--marker-mode', choices=['loopback', 'output_only'], help='Override markers.mode for this run')
    parser.add_argument('--grip-device', choices=['uno', 'rx-g0505m'], default='uno')
    parser.add_argument('--weights', help='RX mode: weight profile path relative to project')
    parser.add_argument('--no-grip-monitor', action='store_true', help='UNO: disable live curve window and automatic two-window layout')
    parser.add_argument('--no-weight-panel', action='store_true', help='RX mode: disable browser weight panel')
    display_mode = parser.add_mutually_exclusive_group()
    display_mode.add_argument('--windowed', action='store_true', help='Window on primary screen')
    display_mode.add_argument('--fullscreen', action='store_true', help='Use configured screen fullscreen')
    args = parser.parse_args()
    if args.list_ports:
        from serial.tools import list_ports
        ports = sorted(list_ports.comports(), key=lambda port: port.device)
        for port in ports:
            print(f'{port.device}\n  {port.description}\n  {port.hwid}')
        if not ports:
            print('No serial ports found.')
        return
    if args.headless and not args.simulate:
        parser.error('--headless requires --simulate')
    from gripflight.runner import run
    return run(args)


if __name__ == '__main__':
    main()
