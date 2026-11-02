"""Select one device adapter; importing the registry opens no hardware or UI."""
from .base import ControlInput, InputDevice


def device_class(name):
    if name == 'uno':
        from .uno import UnoDevice
        return UnoDevice
    if name == 'rx-g0505m':
        from .rx_g0505m import RXDevice
        return RXDevice
    raise ValueError('Unknown grip device: '+name)
