"""Sensores do próximo jogo."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN, VERSION
from .coordinator import ProximoJogoCoordinator
from .parser import Jogo, proximo


def _mando(coordinator: ProximoJogoCoordinator, jogo: Jogo) -> str:
    return "casa" if jogo.mandante.id == coordinator.equipe_id else "fora"


def _adversario(coordinator: ProximoJogoCoordinator, jogo: Jogo) -> str:
    if jogo.mandante.id == coordinator.equipe_id:
        return jogo.visitante.nome
    return jogo.mandante.nome


@dataclass(frozen=True, kw_only=True)
class ProximoJogoSensorDescription(SensorEntityDescription):
    """Como tirar o valor de cada sensor do próximo jogo."""

    value_fn: Callable[[ProximoJogoCoordinator, Jogo], str | datetime | None]


SENSORES: tuple[ProximoJogoSensorDescription, ...] = (
    ProximoJogoSensorDescription(
        key="proximo_jogo",
        translation_key="proximo_jogo",
        device_class=SensorDeviceClass.TIMESTAMP,
        icon="mdi:soccer",
        value_fn=lambda c, j: j.inicio,
    ),
    ProximoJogoSensorDescription(
        key="adversario",
        translation_key="adversario",
        icon="mdi:shield-half-full",
        value_fn=_adversario,
    ),
    ProximoJogoSensorDescription(
        key="campeonato",
        translation_key="campeonato",
        icon="mdi:trophy",
        value_fn=lambda c, j: j.campeonato or None,
    ),
    ProximoJogoSensorDescription(
        key="estadio",
        translation_key="estadio",
        icon="mdi:stadium-variant",
        value_fn=lambda c, j: j.estadio or None,
    ),
    ProximoJogoSensorDescription(
        key="mando",
        translation_key="mando",
        device_class=SensorDeviceClass.ENUM,
        options=["casa", "fora"],
        icon="mdi:home-switch-outline",
        value_fn=_mando,
    ),
    ProximoJogoSensorDescription(
        key="transmissao",
        translation_key="transmissao",
        icon="mdi:television-play",
        value_fn=lambda c, j: ", ".join(j.transmissao)[:255] or None,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Cria os sensores a partir do coordinator já inicializado."""
    coordinator: ProximoJogoCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ProximoJogoSensor(coordinator, description) for description in SENSORES
    )


def device_info(coordinator: ProximoJogoCoordinator) -> DeviceInfo:
    """Um dispositivo por clube, compartilhado por sensores e calendário."""
    return DeviceInfo(
        identifiers={(DOMAIN, str(coordinator.equipe_id))},
        name=coordinator.nome,
        manufacturer="ge.globo",
        model="Agenda de jogos",
        sw_version=VERSION,
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://ge.globo.com/",
    )


class ProximoJogoSensor(CoordinatorEntity[ProximoJogoCoordinator], SensorEntity):
    """Um aspecto do próximo jogo do clube."""

    _attr_has_entity_name = True
    entity_description: ProximoJogoSensorDescription

    def __init__(
        self,
        coordinator: ProximoJogoCoordinator,
        description: ProximoJogoSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.equipe_id}_{description.key}"
        self._attr_device_info = device_info(coordinator)

    @property
    def _jogo(self) -> Jogo | None:
        jogos = self.coordinator.data.jogos if self.coordinator.data else []
        return proximo(jogos, dt_util.now())

    @property
    def available(self) -> bool:
        """Disponível com o último dado bom, mesmo se a última busca falhou."""
        return self.coordinator.data is not None

    @property
    def native_value(self) -> str | datetime | None:
        jogo = self._jogo
        if jogo is None:
            return None
        return self.entity_description.value_fn(self.coordinator, jogo)

    @property
    def extra_state_attributes(self) -> dict | None:
        """O jogo inteiro no sensor principal, que é o que o card lê."""
        if self.entity_description.key != "proximo_jogo":
            return None
        jogo = self._jogo
        last = self.coordinator.last_successful_update
        base = {
            "time": self.coordinator.nome,
            "sigla_time": self.coordinator.sigla,
            "fonte": self.coordinator.data.fonte if self.coordinator.data else None,
            "ultima_atualizacao": last.isoformat() if last else None,
        }
        if jogo is None:
            return {**base, "situacao": "sem_jogo"}
        return {
            **base,
            "mandante": jogo.mandante.nome,
            "visitante": jogo.visitante.nome,
            "sigla_mandante": jogo.mandante.sigla,
            "sigla_visitante": jogo.visitante.sigla,
            "escudo_mandante": jogo.mandante.escudo,
            "escudo_visitante": jogo.visitante.escudo,
            "adversario": _adversario(self.coordinator, jogo),
            "mando": _mando(self.coordinator, jogo),
            "campeonato": jogo.campeonato,
            "fase": jogo.fase,
            "rodada": jogo.rodada,
            "estadio": jogo.estadio,
            "transmissao": list(jogo.transmissao),
            "link": jogo.link,
            "situacao": jogo.situacao,
            "hora_definida": jogo.hora_definida,
            "placar_mandante": jogo.placar_mandante,
            "placar_visitante": jogo.placar_visitante,
        }
