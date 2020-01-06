"""Config flow for the MELCloud platform."""
import asyncio
import logging
from typing import Callable

from aiohttp import ClientError, ClientResponseError
from async_timeout import timeout
from pymelcloud import Client
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import (
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_TOKEN,
)

_LOGGER = logging.getLogger(__name__)


@config_entries.HANDLERS.register("melcloud")
class FlowHandler(config_entries.ConfigFlow):
    """Handle a config flow."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    async def _create_entry(self, email: str, token: str):
        """Register new entry."""
        for entry in self._async_current_entries():
            if entry.data.get(CONF_EMAIL, entry.title) == email:
                self.hass.config_entries.async_update_entry(
                    entry, data={CONF_EMAIL: email, CONF_TOKEN: token,}
                )
                return self.async_abort(
                    reason="already_configured",
                    description_placeholders={"email": email},
                )

        return self.async_create_entry(
            title=email, data={CONF_EMAIL: email, CONF_TOKEN: token,}
        )

    async def _init_client(self, email: str, password: str) -> Client:
        return await Client.login(
            email, password, self.hass.helpers.aiohttp_client.async_get_clientsession(),
        )

    async def _init_client_with_token(self, token: str) -> Client:
        return Client(
            token, self.hass.helpers.aiohttp_client.async_get_clientsession(),
        )

    async def _create_client(self, callable: Callable[[], Client]):
        """Create client."""
        try:
            client = await callable()
            with timeout(10):
                await client.update_confs()
        except asyncio.TimeoutError:
            return self.async_abort(reason="cannot_connect")
        except ClientResponseError as err:
            if err.status is 401 or err.status is 403:
                return self.async_abort(reason="invalid_auth")
            else:
                return self.async_abort(reason="cannot_connect")
        except ClientError:
            _LOGGER.exception("ClientError")
            return self.async_abort(reason="cannot_connect")
        except Exception:  # pylint: disable=broad-except
            _LOGGER.exception("Unexpected error creating device")
            return self.async_abort(reason="unknown")

        email = client._account.get("EmailAddress")
        return await self._create_entry(email, client._token)

    async def async_step_user(self, user_input=None):
        """User initiated config flow."""
        if user_input is None:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema(
                    {vol.Required(CONF_EMAIL): str, vol.Required(CONF_PASSWORD): str,}
                ),
            )
        return await self._create_client(
            lambda: self._init_client(user_input[CONF_EMAIL], user_input[CONF_PASSWORD])
        )

    async def async_step_import(self, user_input):
        """Import a config entry."""
        token = user_input.get(CONF_TOKEN)
        if not token:
            return await self.async_step_user()
        return await self._create_client(lambda: self._init_client_with_token(token))
