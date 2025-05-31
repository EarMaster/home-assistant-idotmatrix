# Home Assistant iDotMatrix Integration

[![Add to HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=nicow&repository=home-assistant-idotmatrix&category=integration)

A custom Home Assistant integration for iDotMatrix LED displays that provides device discovery, connection management, and comprehensive control through the Home Assistant UI.

## Features

- **Automatic Device Discovery**: Scan for iDotMatrix devices via Bluetooth
- **Manual Device Entry**: Add devices by MAC address if auto-discovery fails
- **Display Control**: Turn display on/off and adjust brightness
- **Text Display**: Send custom text messages to the display
- **Clock Modes**: Multiple clock styles (classic, digital, analog, minimal, colorful)
- **Visual Effects**: Various effects like rainbow, breathing, wave, fire, snow, matrix, stars, plasma
- **Screen Controls**: Flip/rotate screen orientation
- **Chronograph**: Start, stop, and reset stopwatch functionality
- **Time Synchronization**: Sync device time with Home Assistant
- **Custom Services**: Advanced control through Home Assistant services

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click the three dots menu and select "Custom repositories"
4. Add this repository URL: `https://github.com/nicow/home-assistant-idotmatrix`
5. Select "Integration" as the category
6. Click "Add"
7. Find "iDotMatrix Display" in HACS and install it
8. Restart Home Assistant

### Manual Installation

1. Download the latest release from GitHub
2. Extract the files to your Home Assistant `custom_components` directory:
   ```
   config/
     custom_components/
       idotmatrix/
         __init__.py
         manifest.json
         config_flow.py
         coordinator.py
         entity.py
         light.py
         switch.py
         text.py
         select.py
         button.py
         const.py
         services.yaml
   ```
3. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services** → **Add Integration**
2. Search for "iDotMatrix Display"
3. Choose between automatic device discovery or manual entry:
   - **Automatic**: The integration will scan for nearby iDotMatrix devices
   - **Manual**: Enter the device name and MAC address manually

### Device Discovery

The integration automatically scans for Bluetooth devices with names starting with "IDM-". If your device is found, select it from the list and click "Submit".

### Manual Entry

If automatic discovery doesn't work:
1. Find your device's MAC address (usually available in the device settings)
2. Enter a friendly name for the device
3. Enter the MAC address in the format `XX:XX:XX:XX:XX:XX`

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

## Services

The integration provides several custom services for advanced control:

### `idotmatrix.display_text`
Display a custom text message with formatting options.

**Parameters:**
- `message` (required): Text message to display
- `font_size` (optional): Font size (small, medium, large)
- `color` (optional): Text color (name or RGB values)
- `speed` (optional): Animation speed (1-100)

**Example:**
```yaml
service: idotmatrix.display_text
data:
  message: "Hello World!"
  font_size: large
  color: blue
  speed: 75
```

### `idotmatrix.display_image`
Display an image or GIF file.

**Parameters:**
- `image_path` (required): Path to the image file
- `duration` (optional): Display duration in seconds

**Example:**
```yaml
service: idotmatrix.display_image
data:
  image_path: "/config/www/images/weather.gif"
  duration: 10
```

### `idotmatrix.set_clock_mode`
Set the clock display style.

**Parameters:**
- `clock_style` (required): Clock style (classic, digital, analog, minimal, colorful)

**Example:**
```yaml
service: idotmatrix.set_clock_mode
data:
  clock_style: digital
```

### `idotmatrix.display_effect`
Display a visual effect.

**Parameters:**
- `effect_type` (required): Effect type (rainbow, breathing, wave, fire, snow, matrix, stars, plasma)
- `duration` (optional): Effect duration in seconds
- `speed` (optional): Animation speed (1-100)

**Example:**
```yaml
service: idotmatrix.display_effect
data:
  effect_type: rainbow
  duration: 30
  speed: 60
```

### `idotmatrix.sync_time`
Synchronize device time with Home Assistant.

**Example:**
```yaml
service: idotmatrix.sync_time
```

## Automations

Here are some example automations using the integration:

### Display Weather Information
```yaml
automation:
  - alias: "Display Weather on iDotMatrix"
    trigger:
      - platform: time
        at: "07:00:00"
    action:
      - service: idotmatrix.display_text
        data:
          message: "{{ states('weather.home') }} {{ state_attr('weather.home', 'temperature') }}°C"
          color: cyan
          font_size: medium
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
      - service: idotmatrix.display_effect
        data:
          effect_type: stars
          duration: 60
      - delay: "00:01:00"
      - service: idotmatrix.display_text
        data:
          message: "Happy Birthday!"
          color: pink
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
      - service: idotmatrix.display_text
        data:
          message: "Door Opened"
          color: yellow
          speed: 100
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
- Check that the device is connected (entity should show as "available")
- Verify you're using the correct service parameters
- Try reconnecting the device through the integration settings

### Getting Device MAC Address
1. Use your phone's Bluetooth settings to scan for devices
2. Look for devices starting with "IDM-"
3. Note the MAC address (format: XX:XX:XX:XX:XX:XX)

## Development

This integration uses the [python3-idotmatrix-library](https://github.com/derkalle4/python3-idotmatrix-library) for device communication.

**Note**: This project was primarily created and developed by GitHub Copilot AI assistant, with guidance and requirements provided by the user.

### Dependencies
- `idotmatrix-library>=0.1.0`
- Home Assistant 2023.1 or later

## Support

For issues and feature requests, please use the [GitHub Issues](https://github.com/nicow/home-assistant-idotmatrix/issues) page.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
