"""Coordinator que busca a agenda do clube no ge.globo."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime
from urllib.parse import urlparse

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .clubes import CLUBES
from .const import (
    ALLOWED_HOST,
    CONF_EQUIPE_ID,
    CONF_NOME,
    CONF_SERIE,
    CONF_SIGLA,
    DEFAULT_SERIE,
    DOMAIN,
    JANELA_JOGO,
    MAX_PAGE_BYTES,
    REQUEST_TIMEOUT,
    SERIES,
    UPDATE_INTERVAL,
    UPDATE_INTERVAL_JOGO,
    USER_AGENT,
)
from .parser import (
    DURACAO_JOGO,
    Clube,
    Equipe,
    Jogo,
    ProximoJogoError,
    SourceUnavailableError,
    find_agenda_url,
    parse_agenda,
    parse_match_venue,
    parse_round,
    parse_standings,
    parse_team_page,
    proximo,
    sigla_de,
    slugify,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class Agenda:
    """O que o coordinator entrega às entidades."""

    jogos: list[Jogo] = field(default_factory=list)
    # "agenda", "time" ou "campeonato": de qual página vieram os jogos.
    fonte: str = ""


class ProximoJogoCoordinator(DataUpdateCoordinator[Agenda]):
    """Busca a agenda uma vez por ciclo e compartilha com as entidades."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.data[CONF_EQUIPE_ID]}",
            update_interval=UPDATE_INTERVAL,
        )
        self.entry = entry
        self.last_successful_update: datetime | None = None
        # Estádio por jogo, para não baixar a página da partida a cada ciclo.
        self._estadios: dict[int, str] = {}

    @property
    def equipe_id(self) -> int:
        return int(self.entry.data[CONF_EQUIPE_ID])

    @property
    def nome(self) -> str:
        return self.entry.data[CONF_NOME]

    @property
    def sigla(self) -> str:
        return self.entry.data.get(CONF_SIGLA) or sigla_de(self.nome)

    @property
    def serie(self) -> str:
        # A tabela embarcada é mais nova que a entrada se o clube mudou de série.
        info = CLUBES.get(self.equipe_id) or {}
        return info.get("serie") or self.entry.data.get(CONF_SERIE, DEFAULT_SERIE)

    async def _async_update_data(self) -> Agenda:
        try:
            jogos, fonte = await self._async_buscar()
        except SourceUnavailableError as err:
            raise UpdateFailed(f"ge.globo indisponível: {err}") from err
        except ProximoJogoError as err:
            raise UpdateFailed(str(err)) from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Erro de rede ao acessar o ge.globo: {err}") from err
        except TimeoutError as err:
            raise UpdateFailed("Tempo esgotado ao acessar o ge.globo.") from err

        jogos = [self._com_siglas(j) for j in jogos]
        self.last_successful_update = dt_util.utcnow()
        self._ajustar_intervalo(jogos)
        return Agenda(jogos=jogos, fonte=fonte)

    async def _async_buscar(self) -> tuple[list[Jogo], str]:
        """Tenta agenda, página do time e página do campeonato, nessa ordem.

        Nem todo clube tem as três: a agenda existe para a maioria, a página do
        time às vezes vem sem jogos, e a do campeonato só tem a rodada atual.
        """
        info = CLUBES.get(self.equipe_id) or {}
        url_time = info.get("time") or (
            f"https://ge.globo.com/futebol/times/{slugify(self.nome)}/"
        )
        url_agenda = info.get("agenda")
        falhas: list[str] = []
        pagina_time: str | None = None

        if not url_agenda:
            try:
                pagina_time = await async_fetch(self.hass, url_time)
                url_agenda = await self.hass.async_add_executor_job(
                    find_agenda_url, pagina_time
                )
            except (SourceUnavailableError, aiohttp.ClientError, TimeoutError) as err:
                falhas.append(f"time: {err}")

        if url_agenda:
            try:
                pagina_agenda = await async_fetch(self.hass, url_agenda)
                jogos = await self.hass.async_add_executor_job(
                    parse_agenda, pagina_agenda
                )
                if jogos is not None:
                    return jogos, "agenda"
            except (SourceUnavailableError, aiohttp.ClientError, TimeoutError) as err:
                falhas.append(f"agenda: {err}")

        if pagina_time is None:
            try:
                pagina_time = await async_fetch(self.hass, url_time)
            except (SourceUnavailableError, aiohttp.ClientError, TimeoutError) as err:
                falhas.append(f"time: {err}")
        if pagina_time is not None:
            jogos = await self.hass.async_add_executor_job(
                parse_team_page, pagina_time
            )
            if jogos is not None:
                return await self._async_com_estadio(jogos), "time"

        serie = SERIES[self.serie]
        try:
            pagina = await async_fetch(self.hass, serie["url"])
        except (SourceUnavailableError, aiohttp.ClientError, TimeoutError) as err:
            falhas.append(f"campeonato: {err}")
            raise SourceUnavailableError("; ".join(falhas)) from err
        jogos = await self.hass.async_add_executor_job(
            parse_round, pagina, serie["campeonato"], self.equipe_id
        )
        if not jogos and falhas:
            # Lista vazia aqui pode ser só falta de cobertura: com falha antes,
            # melhor manter o último jogo conhecido do que apagar o card.
            raise SourceUnavailableError("; ".join(falhas))
        return jogos, "campeonato"

    async def _async_com_estadio(self, jogos: list[Jogo]) -> list[Jogo]:
        """Completa o estádio do próximo jogo pela página da partida."""
        alvo = proximo(jogos, dt_util.now())
        if alvo is None or alvo.estadio or not alvo.link or alvo.id is None:
            return jogos
        if alvo.id not in self._estadios:
            try:
                pagina = await async_fetch(self.hass, alvo.link)
                self._estadios[alvo.id] = await self.hass.async_add_executor_job(
                    parse_match_venue, pagina
                )
            except (SourceUnavailableError, aiohttp.ClientError, TimeoutError):
                _LOGGER.debug("Sem estádio para o jogo %s", alvo.id)
                return jogos
        estadio = self._estadios[alvo.id]
        return [j.com_estadio(estadio) if j.id == alvo.id else j for j in jogos]

    def _com_siglas(self, jogo: Jogo) -> Jogo:
        """A agenda não traz sigla: completa pela tabela de clubes."""
        return replace(
            jogo,
            mandante=self._sigla_equipe(jogo.mandante),
            visitante=self._sigla_equipe(jogo.visitante),
        )

    def _sigla_equipe(self, equipe: Equipe) -> Equipe:
        if equipe.sigla:
            return equipe
        if equipe.id == self.equipe_id:
            return replace(equipe, sigla=self.sigla)
        info = CLUBES.get(equipe.id) if equipe.id is not None else None
        sigla = (info or {}).get("sigla") or sigla_de(equipe.nome)
        return replace(equipe, sigla=sigla)

    def _ajustar_intervalo(self, jogos: list[Jogo]) -> None:
        """Atualiza de 5 em 5 min perto e durante o jogo, para o placar."""
        agora = dt_util.now()
        alvo = proximo(jogos, agora)
        perto = alvo is not None and (
            alvo.situacao == "ao_vivo"
            or alvo.inicio - JANELA_JOGO <= agora <= alvo.inicio + DURACAO_JOGO
        )
        self.update_interval = UPDATE_INTERVAL_JOGO if perto else UPDATE_INTERVAL


async def async_fetch(hass: HomeAssistant, url: str) -> str:
    """Baixa uma página do ge com teto de tamanho e só do domínio esperado."""
    host = urlparse(url).hostname or ""
    if urlparse(url).scheme != "https" or host != ALLOWED_HOST:
        raise SourceUnavailableError(f"URL fora do ge.globo recusada: {url}")

    session = async_get_clientsession(hass)
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    async with session.get(
        url, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as response:
        if response.status != 200:
            raise SourceUnavailableError(f"{url} respondeu HTTP {response.status}.")
        corpo = bytearray()
        async for pedaco in response.content.iter_chunked(64 * 1024):
            corpo.extend(pedaco)
            if len(corpo) > MAX_PAGE_BYTES:
                raise SourceUnavailableError(f"{url} passou de {MAX_PAGE_BYTES} bytes.")
    return corpo.decode("utf-8", "replace")


async def async_fetch_clubes(hass: HomeAssistant, serie: str) -> list[Clube]:
    """Clubes da série pela classificação ao vivo, para o fluxo de configuração."""
    pagina = await async_fetch(hass, SERIES[serie]["url"])
    return await hass.async_add_executor_job(parse_standings, pagina)


def clubes_embarcados(serie: str) -> list[Clube]:
    """Lista de reserva, se o ge não responder durante a configuração."""
    return [
        Clube(id=equipe_id, nome=info["nome"], sigla=info["sigla"] or "", escudo="")
        for equipe_id, info in CLUBES.items()
        if info["serie"] == serie
    ]
