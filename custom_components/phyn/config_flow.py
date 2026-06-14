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
    CONF_HOME_ID,
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


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for phyn."""

    VERSION = 1
    MINOR_VERSION = 3

    def __init__(self) -> None:
        """Initialize flow state."""
        self._username: str | None = None
        self._password: str | None = None
        self._homes: list[dict] | None = None
        self._selected_home: dict | None = None

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

                if len(homes) == 1:
                    self._selected_home = homes[0]
                    return await self.async_step_device()
                return await self.async_step_home()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_home(self, user_input=None):
        """Let the user select which home to set up."""
        errors = {}
        if user_input is not None:
            home_id = user_input[CONF_HOME_ID]
            self._selected_home = next(
                (h for h in self._homes if h["id"] == home_id), None
            )
            return await self.async_step_device()

        home_options = {h["id"]: h.get("name", h["id"]) for h in self._homes}
        schema = vol.Schema({vol.Required(CONF_HOME_ID): vol.In(home_options)})
        return self.async_show_form(step_id="home", data_schema=schema, errors=errors)

    async def async_step_device(self, user_input=None):
        """Let the user select which devices to import."""
        errors = {}
        home = self._selected_home
        device_map = {d["device_id"]: _device_label(d) for d in home.get("devices", [])}
        all_ids = list(device_map.keys())

        if user_input is not None:
            selected = user_input.get(CONF_DEVICE_IDS, [])
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                await self.async_set_unique_id(home["id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=home.get("name", home["id"]),
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_HOME_ID: home["id"],
                        CONF_DEVICE_IDS: selected,
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_IDS, default=all_ids): cv.multi_select(device_map),
        })
        return self.async_show_form(step_id="device", data_schema=schema, errors=errors)

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

    async def async_step_reconfigure(self, user_input: dict[str, any] | None = None):
        """Re-enter credentials then allow changing home + device selection."""
        errors = {}
        reconfigure_entry = self._get_reconfigure_entry()

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

                if len(homes) == 1:
                    self._selected_home = homes[0]
                    return await self.async_step_reconfigure_device()

                # Pre-select the previously configured home
                current_home_id = reconfigure_entry.data.get(CONF_HOME_ID)
                home_options = {
                    h["id"]: h.get("name", h["id"])
                    for h in homes
                }
                schema = vol.Schema({
                    vol.Required(
                        CONF_HOME_ID,
                        default=current_home_id if current_home_id in home_options else vol.UNDEFINED,
                    ): vol.In(home_options),
                })
                return self.async_show_form(
                    step_id="reconfigure_home", data_schema=schema, errors={}
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=DATA_SCHEMA,
            errors=errors,
        )

    async def async_step_reconfigure_home(self, user_input=None):
        """Home selection step during reconfigure (multi-home accounts)."""
        if user_input is not None:
            home_id = user_input[CONF_HOME_ID]
            self._selected_home = next(
                (h for h in self._homes if h["id"] == home_id), None
            )
            return await self.async_step_reconfigure_device()

        # Shouldn't reach here without homes being set; fall back gracefully.
        return await self.async_step_reconfigure()

    async def async_step_reconfigure_device(self, user_input=None):
        """Device selection step during reconfigure."""
        errors = {}
        reconfigure_entry = self._get_reconfigure_entry()
        home = self._selected_home
        device_map = {d["device_id"]: _device_label(d) for d in home.get("devices", [])}
        all_ids = list(device_map.keys())

        # Default to the previously configured devices (if still present),
        # otherwise fall back to all devices.
        current_device_ids = reconfigure_entry.data.get(CONF_DEVICE_IDS, all_ids)
        current_device_ids = [d for d in current_device_ids if d in device_map] or all_ids

        if user_input is not None:
            selected = user_input.get(CONF_DEVICE_IDS, [])
            if not selected:
                errors["base"] = "no_devices_selected"
            else:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    title=home.get("name", home["id"]),
                    data_updates={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_HOME_ID: home["id"],
                        CONF_DEVICE_IDS: selected,
                    },
                )

        schema = vol.Schema({
            vol.Required(CONF_DEVICE_IDS, default=current_device_ids): cv.multi_select(device_map),
        })
        return self.async_show_form(
            step_id="reconfigure_device", data_schema=schema, errors=errors
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
