import unittest
from types import SimpleNamespace

from gripflight.ports import resolve_ports


class PortTests(unittest.TestCase):
    def config(self):
        return {'grip': {'port': 'COM6'}, 'markers': {'port': 'COM10'},
                'serial_devices': {'grip': 'grip-id', 'markers': 'marker-id'}}

    def test_reordered_devices_and_changed_os_names(self):
        for grip, marker in [('COM12', 'COM9'), ('/dev/cu.usbmodem99', '/dev/cu.usbmodem88')]:
            c = self.config()
            resolve_ports(c, ports=[SimpleNamespace(device=marker, serial_number='marker-id'),
                                    SimpleNamespace(device=grip, serial_number='grip-id')])
            self.assertEqual(c['grip']['port'], grip)
            self.assertEqual(c['markers']['port'], marker)

    def test_missing_or_ambiguous_device_does_not_use_old_port(self):
        for ports in [[], [SimpleNamespace(device='COM1', serial_number='grip-id')]*2]:
            with self.assertRaises(ValueError):
                resolve_ports(self.config(), ports=ports)

    def test_manual_override_and_simulation(self):
        c = self.config()
        resolve_ports(c, {'grip': 'COM2', 'markers': 'COM3'}, ports=[])
        self.assertEqual(c['grip']['port'], 'COM2')
        resolve_ports(self.config(), simulate=True, ports=[])

    def test_legacy_config_and_shared_port(self):
        c = self.config()
        del c['serial_devices']
        resolve_ports(c, ports=[])
        self.assertEqual(c['grip']['port'], 'COM6')
        with self.assertRaises(ValueError):
            resolve_ports(c, {'grip': 'COM10'}, ports=[])
