"""UI authentication, including resumable SMS verification."""
import re
import requests
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import DOMAIN, DEFAULT_SCAN_INTERVAL, session_path
from .plus_balance import PlusClient, PlusError, AuthenticationError, SMSRequired

class PlusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    def async_get_options_flow(config_entry):
        return PlusOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            previous_password = getattr(self, "credentials", {}).get(CONF_PASSWORD)
            self.credentials = dict(user_input)
            self.credentials[CONF_USERNAME] = user_input[CONF_USERNAME].strip().lower()
            await self.async_set_unique_id(self.credentials[CONF_USERNAME])
            self._abort_if_unique_id_configured()
            return await self._authenticate("user", reset_session=(
                previous_password is not None and previous_password != user_input[CONF_PASSWORD]))
        return self.async_show_form(step_id="user", data_schema=vol.Schema({
            vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}), errors=errors)

    async def _authenticate(self, step, code=None, *, reset_session=False):
        errors = {}
        try:
            def authenticate():
                path = session_path(self.hass, self.credentials[CONF_USERNAME])
                # A deliberately changed password starts a fresh authentication chain.
                # SMS submissions always keep the pending session intact.
                if reset_session:
                    path.unlink(missing_ok=True)
                client = PlusClient(**self.credentials, session_path=path)
                if code is None:
                    # The user just (re-)entered credentials: lift the failed-login lock,
                    # but keep cookies so the trusted device survives.
                    client.reset_login_lock()
                client.ensure_session(code_provider=None if code is None else lambda: code)
            await self.hass.async_add_executor_job(authenticate)
        except SMSRequired:
            return await self.async_step_sms()
        except AuthenticationError:
            errors["base"] = "invalid_auth"
        except (PlusError, requests.RequestException):
            errors["base"] = "cannot_connect"
        else:
            if self.source == config_entries.SOURCE_REAUTH:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(), data_updates=self.credentials)
            return self.async_create_entry(title=self.credentials[CONF_USERNAME], data=self.credentials)
        return self._show(step, errors)

    def _show(self, step, errors):
        if step == "sms":
            schema = {vol.Required("code"): str}
        elif step == "reauth_confirm":
            schema = {vol.Required(CONF_PASSWORD): str}
        else:
            schema = {vol.Required(CONF_USERNAME): str, vol.Required(CONF_PASSWORD): str}
        return self.async_show_form(step_id=step, data_schema=vol.Schema(schema), errors=errors)

    async def async_step_sms(self, user_input=None):
        if user_input is not None:
            if not re.fullmatch(r"[0-9]{4}", user_input["code"]):
                return self._show("sms", {"code": "invalid_code"})
            return await self._authenticate("sms", user_input["code"])
        return self._show("sms", {})

    async def async_step_reauth(self, entry_data):
        self.credentials = dict(entry_data)
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        if user_input is not None:
            changed = self.credentials[CONF_PASSWORD] != user_input[CONF_PASSWORD]
            self.credentials[CONF_PASSWORD] = user_input[CONF_PASSWORD]
            return await self._authenticate("reauth_confirm", reset_session=changed)
        return self._show("reauth_confirm", {})

class PlusOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=vol.Schema({
            vol.Required("scan_interval", default=self.config_entry.options.get(
                "scan_interval", DEFAULT_SCAN_INTERVAL)): vol.All(vol.Coerce(int), vol.Range(min=15))}))
