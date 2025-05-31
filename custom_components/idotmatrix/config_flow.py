"""Config flow for iDotMatrix integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_NAME,
    CONF_MAC_ADDRESS,
    DEFAULT_NAME,
    DOMAIN,
    SCAN_TIMEOUT,
    CONNECTION_TIMEOUT,
    MAX_RETRIES,
    DEFAULT_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class IDotMatrixConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for iDotMatrix."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: list[dict[str, Any]] = []
        self._selected_device: dict[str, Any] | None = None

    @staticmethod
    def async_get_options_flow(config_entry):
        """Create the options flow."""
        return IDotMatrixOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            if user_input.get("scan_for_devices"):
                return await self.async_step_discovery()
            else:
                return await self.async_step_manual()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("scan_for_devices", default=True): bool,
                }
            ),
            description_placeholders={"name": DEFAULT_NAME},
        )

    async def async_step_discovery(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle device discovery."""
        errors = {}

        if user_input is not None:
            if "device" in user_input:
                device_mac = user_input["device"]
                selected_device = None
                for device in self._discovered_devices:
                    if device["mac_address"] == device_mac:
                        selected_device = device
                        break
                
                if selected_device:
                    return await self._async_create_entry_from_device(selected_device)
            else:
                return await self.async_step_manual()

        # Scan for devices
        try:
            from idotmatrix import ConnectionManager
            
            connection_manager = ConnectionManager()
            devices = await connection_manager.scan(timeout=SCAN_TIMEOUT)
            
            self._discovered_devices = []
            for device in devices:
                self._discovered_devices.append({
                    "name": device.name or f"iDotMatrix {device.address[-5:]}",
                    "mac_address": device.address,
                    "rssi": getattr(device, "rssi", None),
                })
            
            if not self._discovered_devices:
                errors["base"] = "no_devices_found"
            
        except Exception as ex:
            _LOGGER.exception("Error scanning for devices: %s", ex)
            errors["base"] = "scan_failed"

        if errors:
            return self.async_show_form(
                step_id="discovery",
                errors=errors,
                data_schema=vol.Schema({}),
            )

        # Create device selection schema
        device_options = {}
        for device in self._discovered_devices:
            device_options[device["mac_address"]] = f"{device['name']} ({device['mac_address']})"

        return self.async_show_form(
            step_id="discovery",
            data_schema=vol.Schema(
                {
                    vol.Optional("device"): vol.In(device_options),
                    vol.Optional("manual_entry", default=False): bool,
                }
            ),
            description_placeholders={
                "devices_found": len(self._discovered_devices),
            },
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual device entry."""
        errors = {}

        if user_input is not None:
            mac_address = user_input[CONF_MAC_ADDRESS].upper()
            device_name = user_input[CONF_DEVICE_NAME]

            # Validate MAC address format
            if not self._is_valid_mac_address(mac_address):
                errors["base"] = "invalid_mac"
            else:
                # Check if device is already configured
                await self.async_set_unique_id(mac_address)
                self._abort_if_unique_id_configured()

                device = {
                    "name": device_name,
                    "mac_address": mac_address,
                }
                return await self._async_create_entry_from_device(device)

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_DEVICE_NAME, default=DEFAULT_NAME): str,
                    vol.Required(CONF_MAC_ADDRESS): str,
                }
            ),
            errors=errors,
        )

    async def _async_create_entry_from_device(
        self, device: dict[str, Any]
    ) -> FlowResult:
        """Create config entry from device."""
        mac_address = device["mac_address"]
        device_name = device["name"]

        # Set unique ID to prevent duplicates
        await self.async_set_unique_id(mac_address)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=device_name,
            data={
                CONF_NAME: device_name,
                CONF_MAC_ADDRESS: mac_address,
            },
        )

    def _is_valid_mac_address(self, mac: str) -> bool:
        """Validate MAC address format."""
        import re
        pattern = re.compile(r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$')
        return bool(pattern.match(mac))


class IDotMatrixOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for iDotMatrix integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "scan_interval",
                        default=self.config_entry.options.get("scan_interval", DEFAULT_SCAN_INTERVAL),
                    ): vol.All(vol.Coerce(int), vol.Range(min=10, max=300)),
                    vol.Optional(
                        "connection_timeout",
                        default=self.config_entry.options.get("connection_timeout", CONNECTION_TIMEOUT),
                    ): vol.All(vol.Coerce(int), vol.Range(min=5, max=120)),
                    vol.Optional(
                        "retry_attempts",
                        default=self.config_entry.options.get("retry_attempts", MAX_RETRIES),
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=10)),
                }
            ),
        )
