# Home Assistant iDotMatrix Integration

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=EarMaster&repository=home-assistant-idotmatrix&category=integration)

A custom Home Assistant integration for iDotMatrix LED displays that provides device discovery, connection management, and comprehensive control through the Home Assistant UI.

## Features

- **Automatic Device Discovery**: Scan for iDotMatrix devices via Bluetooth
- **Manual Device Entry**: Add devices by MAC address if auto-discovery fails
- **Display Control**: Turn display on/off and adjust brightness
- **Text Display**: Send custom text messages to the display
- **Clock Modes**: Multiple clock styles (RGB Swipe Outline, Christmas Tree, Checkers, Color, Hourglass, Alarm Clock, Outlines, RGB Corners)
- **Visual Effects**: Various effects like Horizontal Rainbow, Random Colored Pixels, Vertical Rainbow, Diagonal Rainbow, and more
- **Stable Connection**: Persistent Bluetooth connection with automatic reconnect — commands work reliably without manual intervention
- **Screen Controls**: Flip/rotate screen orientation
- **Chronograph**: Start, stop, and reset stopwatch functionality
- **Time Synchronization**: Sync device time with Home Assistant

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add this repository URL: `https://github.com/EarMaster/home-assistant-idotmatrix`
5. Select "Integration" as the category
6. Click "Add"
7. Find "iDotMatrix Display" in HACS and install it
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Extract the `idotmatrix` folder into your Home Assistant `config/custom_components/` directory
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "iDotMatrix Display"
3. Choose between automatic device discovery or manual entry:
   - **Automatic**: The integration will scan for nearby iDotMatrix devices
   - **Manual**: Enter the device name and MAC address manually
4. Select your display's **screen size** (16×16, 32×32, or 64×64 pixels). Most IDM- devices are 32×32 — check the back of the device or its packaging if unsure.

### Device Discovery

iDotMatrix devices (names starting with "IDM-") are discovered automatically by Home Assistant's Bluetooth integration. If HA has already seen the device, it will appear under **Settings → Devices & Services** as a new device ready to add — just click "Configure" to confirm.

If the device has not been auto-discovered, use the manual setup flow inside the integration and choose "Scan for devices" to query HA's Bluetooth cache, or enter the MAC address directly.

### Manual Entry

If automatic discovery doesn't work:
1. Find your device's MAC address (usually available in the device settings)
2. Enter a friendly name for the device
3. Enter the MAC address in the format `XX:XX:XX:XX:XX:XX`

### Options

After setup, the following options can be configured via **Settings → Devices & Services → iDotMatrix → Configure**:

| Option | Default | Description |
|---|---|---|
| Scan interval | 30 s | How often HA checks whether the device is in Bluetooth range |
| Connection timeout | 30 s | Maximum time to wait when connecting to the device |
| Retry attempts | 3 | How many times a failed BLE command is retried before giving up |

## Usage

Once configured, the integration creates several entities:

### Light Entity
- **Display**: Control display on/off state and brightness
- Located in the Light domain

### Switch Entity
- **Screen Flip**: Toggle screen rotation/flip

### Text Entity
- **Message**: Send text messages to display

### Select Entities
- **Clock Style**: Choose between different clock display styles
- **Effect Mode**: Select visual effects

### Button Entities
- **Reset Device**: Reset the device to default settings
- **Freeze Screen**: Freeze the current display
- **Start/Stop/Reset Chronograph**: Control stopwatch functionality
- **Sync Time**: Synchronize device time with Home Assistant

## Automations

Here are some example automations using the integration. Replace entity IDs with the ones from your own device.

### Display Weather Information
```yaml
automation:
  - alias: "Display Weather on iDotMatrix"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - action: text.set_value
        target:
          entity_id: text.idotmatrix_message
        data:
          value: "{{ states('weather.home') }} {{ state_attr('weather.home', 'temperature') }}°C"
```

### Birthday Reminder
```yaml
automation:
  - alias: "Birthday Effect"
    trigger:
      - platform: calendar
        event: start
        entity_id: calendar.birthdays
    action:
      - action: select.select_option
        target:
          entity_id: select.idotmatrix_effect_mode
        data:
          option: Horizontal Rainbow
      - delay: "00:01:00"
      - action: text.set_value
        target:
          entity_id: text.idotmatrix_message
        data:
          value: "Happy Birthday!"
```

### Door Notification
```yaml
automation:
  - alias: "Front Door Opened"
    trigger:
      - platform: state
        entity_id: binary_sensor.front_door
        to: "on"
    action:
      - action: text.set_value
        target:
          entity_id: text.idotmatrix_message
        data:
          value: "Door Opened"
```

## Troubleshooting

### Device Not Found
- Ensure the device is powered on and in pairing mode
- Check that Bluetooth is enabled on your Home Assistant host
- Try manual entry with the correct MAC address
- Verify the device name starts with "IDM-"

### Connection Issues
- The device may already be connected to another application
- Try restarting the device
- Check Home Assistant logs for error messages
- Ensure the device is within Bluetooth range

### Commands Not Working
- Check that the device entities show as "available" in Home Assistant
- Make sure the device is in Bluetooth range when sending a command
- Try reloading the integration via **Settings → Devices & Services → iDotMatrix → Reload**

### Getting Device MAC Address
1. Use your phone's Bluetooth settings to scan for devices
2. Look for devices starting with "IDM-"
3. Note the MAC address (format: XX:XX:XX:XX:XX:XX)

## Development

This integration uses the [idotmatrix-api-client](https://github.com/markusressel/idotmatrix-api-client) library for device communication.

### Dependencies
- `idotmatrix>=0.1.0`
- Home Assistant 2023.1 or later

## Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/EarMaster/home-assistant-idotmatrix/issues) page.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
