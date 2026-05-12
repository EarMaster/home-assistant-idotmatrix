"""Config flow for iDotMatrix integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import (
    CONF_DEVICE_NAME,
    CONF_MAC_ADDRESS,
    DEFAULT_NAME,
    DEFAULT_SCAN_INTERVAL,
    CONNECTION_TIMEOUT,
    MAX_RETRIES,
    DOMAIN,
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

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle discovery via Home Assistant's Bluetooth subsystem."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._selected_device = {
            "name": discovery_info.name or f"iDotMatrix {discovery_info.address[-5:]}",
            "mac_address": discovery_info.address,
        }
        self.context["title_placeholders"] = {"name": self._selected_device["name"]}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm adding a Bluetooth-discovered device."""
        if user_input is not None:
            return await self._async_create_entry_from_device(self._selected_device)

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._selected_device["name"]},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
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
        """Handle device discovery using HA's Bluetooth scanner."""
        errors = {}

        if user_input is not None:
            if "device" in user_input:
                device_mac = user_input["device"]
                for device in self._discovered_devices:
                    if device["mac_address"] == device_mac:
                        return await self._async_create_entry_from_device(device)
            return await self.async_step_manual()

        # Use HA's Bluetooth subsystem — avoids spawning a competing BleakScanner
        already_configured = self._async_current_ids()
        discovered = bluetooth.async_discovered_service_info(self.hass, connectable=True)
        self._discovered_devices = [
            {
                "name": svc.name or f"iDotMatrix {svc.address[-5:]}",
                "mac_address": svc.address,
            }
            for svc in discovered
            if svc.name and svc.name.startswith("IDM-")
            and svc.address not in already_configured
        ]

        if not self._discovered_devices:
            errors["base"] = "no_devices_found"

        if errors:
            return self.async_show_form(
                step_id="discovery",
                errors=errors,
                data_schema=vol.Schema({}),
            )

        device_options = {
            d["mac_address"]: f"{d['name']} ({d['mac_address']})"
            for d in self._discovered_devices
        }

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

            if not self._is_valid_mac_address(mac_address):
                errors["base"] = "invalid_mac"
            else:
                await self.async_set_unique_id(mac_address)
                self._abort_if_unique_id_configured()
                return await self._async_create_entry_from_device(
                    {"name": device_name, "mac_address": mac_address}
                )

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
