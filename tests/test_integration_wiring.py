"""Verificações estruturais que não exigem uma instância do Home Assistant."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

import pytest

from custom_components.proximo_jogo import calendar, config_flow, coordinator, sensor
from custom_components.proximo_jogo.clubes import CLUBES
from custom_components.proximo_jogo.const import (
    ALLOWED_HOST,
    CARD_URL,
    DOMAIN,
    SERIES,
    VERSION,
)
from custom_components.proximo_jogo.parser import BRT, Equipe, Jogo

COMPONENT_DIR = Path(__file__).resolve().parents[1] / "custom_components" / DOMAIN
CARD = COMPONENT_DIR / "frontend" / "proximo-jogo-card.js"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_directory_name_matches_manifest_domain() -> None:
    manifest = _load(COMPONENT_DIR / "manifest.json")
    assert manifest["domain"] == COMPONENT_DIR.name == DOMAIN


def test_versions_match() -> None:
    """Manifest, constante e card na mesma versão (a URL do card usa ela)."""
    manifest = _load(COMPONENT_DIR / "manifest.json")
    card_version = re.search(r'CARD_VERSION = "([^"]+)"', CARD.read_text("utf-8"))
    assert manifest["version"] == VERSION == card_version[1]


def test_manifest_declares_card_dependencies() -> None:
    manifest = _load(COMPONENT_DIR / "manifest.json")
    assert {"frontend", "http"} <= set(manifest["dependencies"])


@pytest.mark.parametrize("locale", ["en", "pt-BR"])
def test_translations_match_strings_keys(locale: str) -> None:
    def keys(node: dict, prefix: str = "") -> set[str]:
        found = set()
        for key, value in node.items():
            found.add(prefix + key)
            if isinstance(value, dict):
                found |= keys(value, f"{prefix}{key}.")
        return found

    strings = _load(COMPONENT_DIR / "strings.json")
    translation = _load(COMPONENT_DIR / "translations" / f"{locale}.json")
    assert keys(strings) == keys(translation)


def test_every_sensor_has_a_translated_name() -> None:
    strings = _load(COMPONENT_DIR / "strings.json")["entity"]
    for description in sensor.SENSORES:
        assert description.translation_key in strings["sensor"]
        for option in description.options or []:
            assert option in strings["sensor"][description.translation_key]["state"]
    assert "jogos" in strings["calendar"]


def test_clubes_table_covers_both_series() -> None:
    por_serie = {serie: 0 for serie in SERIES}
    for equipe_id, info in CLUBES.items():
        assert isinstance(equipe_id, int)
        assert info["nome"] and info["sigla"]
        por_serie[info["serie"]] += 1
        for chave in ("time", "agenda"):
            if info[chave]:
                url = urlparse(info[chave])
                assert (url.scheme, url.hostname) == ("https", ALLOWED_HOST)
                assert info[chave].endswith("/")
    assert por_serie == {"a": 20, "b": 20}


def test_card_is_the_custom_element_the_integration_serves() -> None:
    js = CARD.read_text(encoding="utf-8")
    assert 'customElements.define("proximo-jogo-card"' in js
    assert f'const DOMAIN = "{DOMAIN}"' in js
    assert CARD_URL.endswith(CARD.name)


def test_card_reads_the_attributes_the_sensor_exposes() -> None:
    """Se um atributo mudar de nome no sensor, o card quebraria em silêncio."""
    js = CARD.read_text(encoding="utf-8")
    # a = próximo jogo, u = último resultado, t = classificação, ln = linha da tabela
    usados = set(re.findall(r"\b(?:a|u|t|ln)\.([a-z_]+)", js))
    expostos = set(
        re.findall(r'"([a-z_]+)":', (COMPONENT_DIR / "sensor.py").read_text("utf-8"))
    )
    assert usados and usados <= expostos


def test_calendar_event_for_timed_and_all_day_matches() -> None:
    jogo = Jogo(
        id=10,
        inicio=datetime(2026, 11, 4, 19, 30, tzinfo=BRT),
        mandante=Equipe(id=262, nome="Flamengo", sigla="FLA"),
        visitante=Equipe(id=284, nome="Grêmio", sigla="GRE"),
        campeonato="Campeonato Brasileiro",
        rodada=34,
        estadio="Maracanã",
        transmissao=("Premiere",),
    )
    ev = calendar.evento(jogo)
    assert ev.summary == "FLA x GRE"
    assert ev.location == "Maracanã"
    assert ev.end - ev.start == calendar.DURACAO_JOGO
    assert "Rodada 34" in ev.description and "Premiere" in ev.description

    sem_hora = calendar.evento(
        Jogo(**{**jogo.__dict__, "hora_definida": False, "inicio": jogo.inicio})
    )
    assert sem_hora.start == date(2026, 11, 4)
    assert sem_hora.end == date(2026, 11, 5)


def test_config_flow_and_coordinator_import() -> None:
    assert config_flow.ProximoJogoConfigFlow.VERSION == 1
    assert coordinator.clubes_embarcados("a")


def test_sensores_novos_tem_nome_traduzido() -> None:
    strings = _load(COMPONENT_DIR / "strings.json")["entity"]["sensor"]
    assert sensor.ClassificacaoSensor._attr_translation_key in strings
    chave = sensor.UltimoResultadoSensor._attr_translation_key
    assert set(sensor.UltimoResultadoSensor._attr_options) == set(
        strings[chave]["state"]
    )


def test_card_acha_os_sensores_novos_pelo_translation_key() -> None:
    js = CARD.read_text(encoding="utf-8")
    for chave in (
        sensor.ClassificacaoSensor._attr_translation_key,
        sensor.UltimoResultadoSensor._attr_translation_key,
    ):
        assert f'"{chave}"' in js
