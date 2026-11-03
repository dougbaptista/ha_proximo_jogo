"""Fluxo de configuração: escolher a série e depois o clube."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    CONF_EQUIPE_ID,
    CONF_NOME,
    CONF_SERIE,
    CONF_SIGLA,
    DEFAULT_SERIE,
    DOMAIN,
    SERIES,
)
from .coordinator import async_fetch_clubes, clubes_embarcados
from .parser import Clube

_LOGGER = logging.getLogger(__name__)


class ProximoJogoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Uma entrada por clube; dá para seguir mais de um."""

    VERSION = 1

    def __init__(self) -> None:
        self._serie: str = DEFAULT_SERIE
        self._clubes: list[Clube] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Série A ou Série B."""
        if user_input is not None:
            self._serie = user_input[CONF_SERIE]
            return await self.async_step_clube()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SERIE, default=DEFAULT_SERIE): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=chave, label=serie["nome"])
                                for chave, serie in SERIES.items()
                            ],
                            mode=SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
        )

    async def async_step_clube(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """O clube, entre os da série escolhida."""
        errors: dict[str, str] = {}
        if not self._clubes:
            try:
                self._clubes = await async_fetch_clubes(self.hass, self._serie)
            except Exception:  # noqa: BLE001 - qualquer falha usa a lista embutida
                _LOGGER.warning(
                    "Não foi possível obter a classificação no ge.globo; "
                    "usando a lista de clubes embutida.",
                    exc_info=True,
                )
                self._clubes = clubes_embarcados(self._serie)
                errors["base"] = "cannot_connect"

        if user_input is not None:
            escolhido = next(
                c for c in self._clubes if str(c.id) == user_input[CONF_EQUIPE_ID]
            )
            await self.async_set_unique_id(str(escolhido.id))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=escolhido.nome,
                data={
                    CONF_EQUIPE_ID: escolhido.id,
                    CONF_NOME: escolhido.nome,
                    CONF_SIGLA: escolhido.sigla,
                    CONF_SERIE: self._serie,
                },
            )

        return self.async_show_form(
            step_id="clube",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EQUIPE_ID): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(value=str(c.id), label=c.nome)
                                for c in self._clubes
                            ],
                            mode=SelectSelectorMode.DROPDOWN,
                            sort=True,
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={"serie": SERIES[self._serie]["nome"]},
        )
