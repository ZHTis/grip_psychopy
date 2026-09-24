"""Resolve stable USB identities to the operating system's current port names."""


def resolve_ports(config, overrides=None, simulate=False, ports=None):
    overrides = overrides or {}
    identities = config.get('serial_devices', {})
    roles = ('grip', 'markers') if config['markers'].get('enabled', True) else ('grip',)
    if not simulate and any(identities.get(k) and not overrides.get(k)
                            for k in roles) and ports is None:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
    for role in roles:
        if overrides.get(role):
            config[role]['port'] = overrides[role]
        elif not simulate and identities.get(role):
            serial_number = identities[role]
            matches = [p.device for p in ports if p.serial_number == serial_number]
            if len(matches) != 1:
                raise ValueError(f'{role}: expected one USB device with serial number '
                                 f'{serial_number}, found {len(matches)}. '
                                 'Connect the correct board and use --list-ports to check.')
            config[role]['port'] = matches[0]
    if not simulate and 'markers' in roles and config['grip']['port'].casefold() == config['markers']['port'].casefold():
        raise ValueError('Grip and marker boards must use different serial ports.')
