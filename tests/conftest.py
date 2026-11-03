"""Configuração dos testes.

O módulo ``parser`` não depende do Home Assistant, então a maior parte da
suíte roda sem stubs. Os stubs abaixo só são instalados se o pacote
``homeassistant`` não estiver disponível, para importar ``sensor``,
``calendar`` e ``config_flow`` num ambiente enxuto.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def _install_homeassistant_stubs() -> None:
    """Cria um pacote ``homeassistant`` mínimo em ``sys.modules``."""
    modules: dict[str, types.ModuleType] = {}

    def stub_class(name: str, *bases: type) -> type:
        """Aceita ``Foo[dict]`` e ``class Bar(ConfigFlow, domain="x")``."""
        return type(
            name,
            bases or (),
            {
                "__class_getitem__": classmethod(lambda cls, item: cls),
                "__init_subclass__": classmethod(lambda cls, **kwargs: None),
            },
        )

    def module(name: str, **attrs: object) -> types.ModuleType:
        mod = types.ModuleType(name)
        for key, value in attrs.items():
            setattr(mod, key, value)
        modules[name] = mod
        return mod

    @dataclass(frozen=True, kw_only=True)
    class SensorEntityDescription:
        key: str
        translation_key: str | None = None
        device_class: str | None = None
        icon: str | None = None
        options: list[str] | None = None

    @dataclass
    class CalendarEvent:
        start: object
        end: object
        summary: str
        location: str | None = None
        description: str | None = None
        uid: str | None = None

    module("homeassistant")
    module("homeassistant.components")
    module(
        "homeassistant.components.sensor",
        SensorEntity=stub_class("SensorEntity"),
        SensorEntityDescription=SensorEntityDescription,
        SensorDeviceClass=types.SimpleNamespace(TIMESTAMP="timestamp", ENUM="enum"),
    )
    module(
        "homeassistant.components.calendar",
        CalendarEntity=stub_class("CalendarEntity"),
        CalendarEvent=CalendarEvent,
    )
    module("homeassistant.components.frontend", add_extra_js_url=lambda hass, url: None)
    module("homeassistant.components.http", StaticPathConfig=stub_class("Static"))
    module(
        "homeassistant.config_entries",
        ConfigEntry=stub_class("ConfigEntry"),
        ConfigFlow=stub_class("ConfigFlow"),
        ConfigFlowResult=dict,
    )
    module("homeassistant.core", HomeAssistant=stub_class("HomeAssistant"))
    module("homeassistant.helpers")
    module(
        "homeassistant.helpers.aiohttp_client",
        async_get_clientsession=lambda hass: None,
    )
    module(
        "homeassistant.helpers.config_validation",
        config_entry_only_config_schema=lambda domain: None,
    )
    module(
        "homeassistant.helpers.device_registry",
        DeviceInfo=dict,
        DeviceEntryType=types.SimpleNamespace(SERVICE="service"),
    )
    module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    module(
        "homeassistant.helpers.selector",
        SelectOptionDict=dict,
        SelectSelector=stub_class("SelectSelector"),
        SelectSelectorConfig=stub_class("SelectSelectorConfig"),
        SelectSelectorMode=types.SimpleNamespace(DROPDOWN="dropdown", LIST="list"),
    )
    module("homeassistant.helpers.typing", ConfigType=dict)
    module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=stub_class("DataUpdateCoordinator"),
        CoordinatorEntity=stub_class("CoordinatorEntity"),
        UpdateFailed=stub_class("UpdateFailed", Exception),
    )
    module("homeassistant.util")
    module(
        "homeassistant.util.dt",
        now=lambda: datetime.now(timezone.utc),
        utcnow=lambda: datetime.now(timezone.utc),
    )

    # Liga os submódulos aos pais para que "import a.b" resolva atributos.
    for name, mod in modules.items():
        parent, _, child = name.rpartition(".")
        if parent:
            setattr(modules[parent], child, mod)

    sys.modules.update(modules)


if importlib.util.find_spec("homeassistant") is None:  # pragma: no cover
    _install_homeassistant_stubs()


def ler(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


@pytest.fixture
def agenda_vasco() -> str:
    """Agenda do Vasco (recorte real de 02/11/2026, 3 jogos futuros)."""
    return ler("agenda_vasco.html")


@pytest.fixture
def time_gremio() -> str:
    """Página do Grêmio com o array "jogos" (recorte real de 02/11/2026)."""
    return ler("time_gremio.html")


@pytest.fixture
def partida() -> str:
    """Trecho da página de Flamengo x Grêmio com o estádio."""
    return ler("partida.html")


@pytest.fixture
def serie_a() -> str:
    """Classificação e rodada 34 da Série A (recorte real de 02/11/2026)."""
    return ler("serie_a.html")
