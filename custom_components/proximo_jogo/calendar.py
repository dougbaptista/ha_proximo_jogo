"""Calendário com os próximos jogos do clube.

Permite gatilhos nativos do HA ("1 hora antes do jogo") sem input_datetime, e
fica ligado durante a partida.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import ProximoJogoCoordinator
from .parser import DURACAO_JOGO, Jogo, proximos
from .sensor import device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria o calendário do clube."""
    coordinator: ProximoJogoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([JogosCalendar(coordinator)])


def evento(jogo: Jogo) -> CalendarEvent:
    """Um jogo como evento; sem hora definida vira evento de dia inteiro."""
    sigla_m = jogo.mandante.sigla or jogo.mandante.nome
    sigla_v = jogo.visitante.sigla or jogo.visitante.nome
    detalhes = [jogo.campeonato]
    if jogo.rodada:
        detalhes.append(f"Rodada {jogo.rodada}")
    if jogo.transmissao:
        detalhes.append("Onde assistir: " + ", ".join(jogo.transmissao))
    if jogo.link:
        detalhes.append(jogo.link)

    if jogo.hora_definida:
        inicio, fim = jogo.inicio, jogo.inicio + DURACAO_JOGO
    else:
        inicio = jogo.inicio.date()
        fim = inicio + timedelta(days=1)
    return CalendarEvent(
        start=inicio,
        end=fim,
        summary=f"{sigla_m} x {sigla_v}",
        location=jogo.estadio or None,
        description="\n".join(d for d in detalhes if d) or None,
        uid=str(jogo.id) if jogo.id is not None else None,
    )


class JogosCalendar(CoordinatorEntity[ProximoJogoCoordinator], CalendarEntity):
    """Próximos jogos do clube."""

    _attr_has_entity_name = True
    _attr_translation_key = "jogos"

    def __init__(self, coordinator: ProximoJogoCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.equipe_id}_calendario"
        self._attr_device_info = device_info(coordinator)

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None

    def _jogos(self) -> list[Jogo]:
        jogos = self.coordinator.data.jogos if self.coordinator.data else []
        return proximos(jogos, dt_util.now())

    @property
    def event(self) -> CalendarEvent | None:
        """O jogo em andamento ou o próximo."""
        jogos = self._jogos()
        return evento(jogos[0]) if jogos else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Jogos que caem no intervalo pedido pela interface."""
        jogos = self.coordinator.data.jogos if self.coordinator.data else []
        eventos = [evento(jogo) for jogo in jogos]
        # start_datetime_local converte também os eventos de dia inteiro.
        return [
            ev
            for ev in eventos
            if ev.start_datetime_local < end_date and ev.end_datetime_local > start_date
        ]
