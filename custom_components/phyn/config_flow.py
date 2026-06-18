"""Config flow for phyn integration."""
from aiophyn import async_get_api
from aiophyn.errors import RequestError
from botocore.exceptions import ClientError
import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    LOGGER,
    ALL_ALERT_TYPES,
    CONF_EXCLUDED_ALERT_TYPES,
    CONF_DEVICE_IDS,
)

DATA_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})
REAUTH_SCHEMA = vol.Schema({
    vol.Required(CONF_USERNAME): str,
    vol.Required(CONF_PASSWORD): str,
})


async def _get_api_and_homes(hass: core.HomeAssistant, username: str, password: str):
    """Authenticate and return (api, homes).

    Raises CannotConnect or propagates ClientError on auth failure.
    """
    session = async_get_clientsession(hass)
    try:
        api = await async_get_api(
            username, password, phyn_brand="phyn", session=session
        )
    except RequestError as request_error:
        LOGGER.error("Error connecting to the Phyn API: %s", request_error)
        raise CannotConnect from request_error

    homes = await api.home.get_homes(username)
    return api, homes


def _device_label(device: dict) -> str:
    """Return a human-readable label for a device."""
    name = device.get("device_name") or device.get("product_code", "")
    return f"{name} ({device['device_id']})" if name else device["device_id"]


def _build_device_schema(homes: list[dict], current_device_ids: list[str] | None = None) -> vol.Schema:
    """Build a schema with one multi_select per home.

    Each field key is the home name so that HA's config flow renders it as the
    field heading (HA falls back to the raw key when no translation entry exists).
    If *current_device_ids* is provided the defaults are pre-populated with the
    currently selected devices for each home (falling back to all devices in that
    home when none are currently selected).
    """
    current = set(current_device_ids) if current_device_ids else set()
    fields: dict = {}
    for home in homes:
        if not home.get("devices"):
            continue
        home_name = home.get("name", home["id"])
        device_map = {d["device_id"]: _device_label(d) for d in home["devices"]}
        all_ids = list(device_map.keys())
        if current:
            default_ids = [d for d in all_ids if d in current] or all_ids
        else:
            default_ids = all_ids
        fields[vol.Optional(home_name, default=default_ids)] = cv.multi_select(device_map)
    return vol.Schema(fields)


def _extract_device_ids(user_input: dict, homes: list[dict]) -> list[str]:
    """Flatten selected device IDs from per-home fields in a submitted form."""
    selected: list[str] = []
    seen: set[str] = set()
    for home in homes:
        if not home.get("devices"):
            continue
        home_name = home.get("name", home["id"])
        for device_id in user_input.get(home_name, []):
            if device_id not in seen:
                seen.add(device_id)
                selected.append(device_id)
    return selected


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for phyn."""

    VERSION = 1
    MINOR_VERSION = 4

    def __init__(self) -> None:
        """Initialize flow state."""
        self._username: str | None = None
        self._password: str | None = None
        self._homes: list[dict] = []

    @staticmethod
    def async_get_options_flow(config_entry):
        """Return the options flow handler."""
        return PhynOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step (credentials)."""
        errors = {}
        if user_input is not None:
            try:
                _, homes = await _get_api_and_homes(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except ClientError as error:
                if error.response['Error']['Code'] == "NotAuthorizedException":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                self._username = user_input[CONF_USERNAME]
                self._password = user_input[CONF_PASSWORD]
                self._homes = homes

                await self.async_set_unique_id(self._username)
                self._abort_if_unique_id_configured()

                return await self.async_step_device()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_device(self, user_input=None):
        """Select devices to monitor, grouped by home."""
        errors = {}
        if user_input is not None:
            selected = _extract_device_ids(user_input, self._homes)
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                return self.async_create_entry(
                    title=self._username,
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_DEVICE_IDS: selected,
                    },
                )

        return self.async_show_form(
            step_id="device",
            data_schema=_build_device_schema(self._homes),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            reauth_entry = self._get_reauth_entry()
            try:
                await _get_api_and_homes(
                    self.hass,
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except ClientError as error:
                if error.response['Error']['Code'] == "NotAuthorizedException":
                    errors["base"] = "invalid_auth"
                else:
                    errors["base"] = "cannot_connect"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    reauth_entry,
                    data_updates={
                        CONF_USERNAME: user_input[CONF_USERNAME],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Change device selection without re-authentication.

        Stored credentials are reused silently. If they are no longer valid the
        flow redirects to reauth instead of surfacing an unactionable error.
        """
        reconfigure_entry = self._get_reconfigure_entry()

        if user_input is None:
            # First call: fetch the live device list and show the form.
            username = reconfigure_entry.data[CONF_USERNAME]
            password = reconfigure_entry.data[CONF_PASSWORD]
            try:
                _, homes = await _get_api_and_homes(self.hass, username, password)
            except (ClientError, CannotConnect):
                return await self.async_step_reauth_confirm()

            self._homes = homes
            current_ids = reconfigure_entry.data.get(CONF_DEVICE_IDS, [])
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_build_device_schema(self._homes, current_ids),
            )

        selected = _extract_device_ids(user_input, self._homes)
        errors = {}
        if not selected:
            errors["base"] = "no_devices_selected"
            current_ids = reconfigure_entry.data.get(CONF_DEVICE_IDS, [])
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=_build_device_schema(self._homes, current_ids),
                errors=errors,
            )

        return self.async_update_reload_and_abort(
            reconfigure_entry,
            data_updates={CONF_DEVICE_IDS: selected},
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class PhynOptionsFlow(config_entries.OptionsFlow):
    """Handle Phyn integration options (e.g. suppressed alert types)."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_excluded = self._config_entry.options.get(CONF_EXCLUDED_ALERT_TYPES, [])

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_EXCLUDED_ALERT_TYPES,
                    default=current_excluded,
                ): cv.multi_select(ALL_ALERT_TYPES),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
