"""Leitura das páginas do ge.globo, sem depender do Home Assistant.

O ge não tem API pública: os dados vêm em JSON embutido no HTML. Cada página
guarda o JSON num formato diferente, e cada clube tem um tipo de página:

* agenda do clube (``.../agenda-de-jogos-do-x/``): ``window.dataSportsSchedule``
  com ``teamAgenda.future/now/past`` — a fonte mais completa (estádio, rodada,
  onde assistir, todos os campeonatos);
* página do time (``.../futebol/times/x/``): array ``"jogos"`` com os próximos
  jogos, sem o estádio, que sai da página da partida;
* página do campeonato (``.../brasileirao-serie-a/``): ``"classificacao"`` com os
  20 clubes e ``"lista_jogos"`` só da rodada atual — o último recurso.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# Horários do ge são sempre de Brasília, sem fuso no texto.
BRT = ZoneInfo("America/Sao_Paulo")

# Um jogo continua sendo "o próximo" até este tempo depois do início, para o
# card mostrar o jogo em andamento em vez de pular para o seguinte.
DURACAO_JOGO = timedelta(hours=2, minutes=30)
LIMITE_AO_VIVO = timedelta(hours=5)


class ProximoJogoError(Exception):
    """Erro base da integração."""


class SourceUnavailableError(ProximoJogoError):
    """A página do ge não respondeu ou veio sem os dados esperados."""


@dataclass(frozen=True)
class Equipe:
    """Um dos lados do jogo."""

    id: int | None
    nome: str
    sigla: str = ""
    escudo: str = ""


@dataclass(frozen=True)
class Jogo:
    """Um jogo normalizado, venha de qual página vier."""

    id: int | None
    inicio: datetime
    mandante: Equipe
    visitante: Equipe
    campeonato: str = ""
    fase: str = ""
    rodada: int | None = None
    estadio: str = ""
    transmissao: tuple[str, ...] = field(default_factory=tuple)
    link: str = ""
    placar_mandante: int | None = None
    placar_visitante: int | None = None
    # "futuro", "ao_vivo" ou "encerrado".
    situacao: str = "futuro"
    hora_definida: bool = True

    def com_estadio(self, estadio: str) -> Jogo:
        """Cópia com o estádio preenchido."""
        return replace(self, estadio=estadio)


def slugify(texto: str) -> str:
    """``"São Paulo"`` -> ``"sao-paulo"``, como o ge monta as URLs."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")


def _fatiar(texto: str, inicio: int) -> str:
    """Do ``[`` ou ``{`` em ``inicio`` até o fechamento, respeitando strings."""
    profundidade = 0
    em_string = False
    escape = False
    for pos in range(inicio, len(texto)):
        c = texto[pos]
        if escape:
            escape = False
            continue
        if c == "\\":
            escape = True
            continue
        if c == '"':
            em_string = not em_string
            continue
        if em_string:
            continue
        if c in "[{":
            profundidade += 1
        elif c in "]}":
            profundidade -= 1
            if profundidade == 0:
                return texto[inicio : pos + 1]
    return ""


def _json_apos(pagina: str, padrao: str, abre: str) -> list | dict | None:
    """Decodifica o primeiro JSON válido que segue ``padrao``."""
    for m in re.finditer(padrao, pagina):
        pos = pagina.find(abre, m.end() - 1)
        if pos < 0:
            continue
        bruto = _fatiar(pagina, pos)
        if not bruto:
            continue
        try:
            return json.loads(bruto)
        except ValueError:
            continue
    return None


def _inteiro(valor) -> int | None:
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _quando(data: str | None, hora: str | None) -> tuple[datetime, bool] | None:
    """Data e hora do ge em datetime de Brasília; hora vazia = "a definir"."""
    if not data:
        return None
    data = data[:10]
    hora_definida = bool(hora)
    hora = (hora or "00:00")[:5]
    try:
        quando = datetime.strptime(f"{data} {hora}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None
    return quando.replace(tzinfo=BRT), hora_definida


# --------------------------------------------------------------------------
# Agenda do clube
# --------------------------------------------------------------------------

_SITUACAO_AGENDA = {"FUTURE": "futuro", "NOW": "ao_vivo", "PAST": "encerrado"}


def _equipe_agenda(time: dict | None) -> Equipe:
    time = time or {}
    return Equipe(
        id=_inteiro(time.get("id")),
        nome=time.get("popularName") or time.get("name") or "",
        escudo=time.get("badgeSvg") or time.get("badgePng") or "",
    )


def _jogo_agenda(evento: dict) -> Jogo | None:
    partida = evento.get("match") if isinstance(evento, dict) else None
    if not isinstance(partida, dict):
        return None
    quando = _quando(partida.get("startDate"), partida.get("startHour"))
    if quando is None:
        return None
    mandante = _equipe_agenda(partida.get("firstContestant"))
    visitante = _equipe_agenda(partida.get("secondContestant"))
    if not mandante.nome or not visitante.nome:
        return None

    fase = partida.get("phase") or {}
    campeonato = (
        ((fase.get("championshipEdition") or {}).get("championship") or {}).get("name")
    ) or ""
    placar = partida.get("scoreboard") or {}
    return Jogo(
        id=_inteiro(partida.get("id")),
        inicio=quando[0],
        hora_definida=quando[1],
        mandante=mandante,
        visitante=visitante,
        campeonato=campeonato,
        fase=fase.get("name") or "",
        rodada=_inteiro(partida.get("round")),
        estadio=(partida.get("location") or {}).get("popularName") or "",
        transmissao=tuple(
            s["name"] for s in partida.get("liveWatchSources") or [] if s.get("name")
        ),
        link=(partida.get("transmission") or {}).get("url") or "",
        placar_mandante=_inteiro(placar.get("home")),
        placar_visitante=_inteiro(placar.get("away")),
        situacao=_SITUACAO_AGENDA.get(partida.get("moment") or "", "futuro"),
    )


def parse_agenda(pagina: str) -> list[Jogo] | None:
    """Jogos ao vivo e futuros da agenda do clube.

    Devolve ``None`` se a página não tem a agenda (layout mudou), e lista vazia
    se tem, mas sem jogo marcado — o chamador trata os dois de jeitos diferentes.
    """
    dados = _json_apos(pagina, r"scheduleTeam\s*:\s*\{", "{")
    if not isinstance(dados, dict) or "teamAgenda" not in dados:
        return None
    agenda = dados.get("teamAgenda") or {}
    jogos = []
    for chave in ("now", "future"):
        for evento in agenda.get(chave) or []:
            jogo = _jogo_agenda(evento)
            if jogo is not None:
                jogos.append(jogo)
    return sorted(jogos, key=lambda j: j.inicio)


def parse_agenda_passados(pagina: str) -> list[Jogo]:
    """Jogos já encerrados da agenda, do mais antigo ao mais recente."""
    dados = _json_apos(pagina, r"scheduleTeam\s*:\s*\{", "{")
    if not isinstance(dados, dict):
        return []
    passados = []
    for evento in (dados.get("teamAgenda") or {}).get("past") or []:
        jogo = _jogo_agenda(evento)
        if jogo is not None and jogo.placar_mandante is not None:
            passados.append(replace(jogo, situacao="encerrado"))
    return sorted(passados, key=lambda j: j.inicio)


def find_agenda_url(pagina: str) -> str | None:
    """Link da agenda dentro da página do time (o nome varia: "do"/"da")."""
    pagina = pagina.replace("\\/", "/")
    m = re.search(
        r"https://ge\.globo\.com/[a-z0-9/-]*?/agenda-de-jogos-d[oa]-[a-z0-9-]+/",
        pagina,
    )
    return m[0] if m else None


# --------------------------------------------------------------------------
# Página do time
# --------------------------------------------------------------------------


def _escudo_sde(equipe: dict) -> str:
    escudos = equipe.get("escudos") or {}
    return (
        escudos.get("svg")
        or escudos.get("60x60")
        or escudos.get("150x150")
        or escudos.get("45x45")
        or equipe.get("escudo")
        or ""
    )


def _equipe_sde(equipe: dict | None) -> Equipe:
    equipe = equipe or {}
    return Equipe(
        id=_inteiro(equipe.get("equipe_id") or equipe.get("id")),
        nome=equipe.get("nome_popular") or equipe.get("nome") or "",
        sigla=equipe.get("sigla") or "",
        escudo=_escudo_sde(equipe),
    )


def _situacao_sde(jogo: dict) -> str:
    broadcast = ((jogo.get("transmissao") or {}).get("broadcast") or {}).get("id")
    if broadcast == "ENCERRADA":
        return "encerrado"
    if jogo.get("jogo_ja_comecou"):
        return "ao_vivo"
    return "futuro"


def parse_team_page(pagina: str) -> list[Jogo] | None:
    """Próximos jogos do array ``"jogos"`` da página do time."""
    lista = None
    for m in re.finditer(r'"jogos"\s*:\s*\[', pagina):
        bruto = _fatiar(pagina, pagina.index("[", m.start()))
        try:
            candidato = json.loads(bruto) if bruto else None
        except ValueError:
            continue
        if (
            isinstance(candidato, list)
            and candidato
            and isinstance(candidato[0], dict)
            and candidato[0].get("data_realizacao")
        ):
            lista = candidato
            break
    if lista is None:
        return None

    jogos = []
    for item in lista:
        quando = _quando(item.get("data_realizacao"), item.get("hora_realizacao"))
        if quando is None:
            continue
        mandante = _equipe_sde(item.get("equipe_mandante"))
        visitante = _equipe_sde(item.get("equipe_visitante"))
        if not mandante.nome or not visitante.nome:
            continue
        plataformas = (item.get("transmissoes") or {}).get("plataformas") or []
        jogos.append(
            Jogo(
                id=_inteiro(item.get("jogo_id")),
                inicio=quando[0],
                hora_definida=quando[1],
                mandante=mandante,
                visitante=visitante,
                campeonato=(item.get("campeonato") or {}).get("nome") or "",
                transmissao=tuple(p["nome"] for p in plataformas if p.get("nome")),
                link=(item.get("transmissao") or {}).get("url") or "",
                placar_mandante=_inteiro(item.get("placar_oficial_mandante")),
                placar_visitante=_inteiro(item.get("placar_oficial_visitante")),
                situacao=_situacao_sde(item),
            )
        )
    return sorted(jogos, key=lambda j: j.inicio)


def parse_match_venue(pagina: str) -> str:
    """Estádio na página da partida (``"popularName":"Maracanã","region"``)."""
    m = re.search(r'"popularName"\s*:\s*("(?:[^"\\]|\\.)*")\s*,\s*"region"', pagina)
    if not m:
        return ""
    try:
        return json.loads(m[1])
    except ValueError:
        return ""


# --------------------------------------------------------------------------
# Página do campeonato
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Clube:
    """Clube da classificação, para a lista do fluxo de configuração."""

    id: int
    nome: str
    sigla: str
    escudo: str
    posicao: int | None = None


def parse_standings(pagina: str) -> list[Clube]:
    """Os clubes da classificação, na ordem da tabela."""
    dados = _json_apos(pagina, r'"classificacao"\s*:\s*\[', "[")
    if not isinstance(dados, list):
        raise SourceUnavailableError("A página do campeonato veio sem classificação.")
    clubes = []
    for linha in dados:
        equipe_id = _inteiro((linha or {}).get("equipe_id"))
        nome = (linha or {}).get("nome_popular")
        if equipe_id is None or not nome:
            continue
        clubes.append(
            Clube(
                id=equipe_id,
                nome=nome,
                sigla=linha.get("sigla") or "",
                escudo=linha.get("escudo") or "",
                posicao=_inteiro(linha.get("ordem")),
            )
        )
    if not clubes:
        raise SourceUnavailableError("A classificação do campeonato veio vazia.")
    return clubes


@dataclass(frozen=True)
class LinhaTabela:
    """Uma linha da classificação, com tudo que o card da tabela mostra."""

    posicao: int
    equipe_id: int
    nome: str
    sigla: str
    escudo: str
    pontos: int
    jogos: int
    vitorias: int
    empates: int
    derrotas: int
    gols_pro: int
    gols_contra: int
    saldo_gols: int
    aproveitamento: int
    # Do mais antigo ao mais recente: "v", "e" ou "d".
    ultimos_jogos: tuple[str, ...] = field(default_factory=tuple)
    # Faixa da tabela (Libertadores, rebaixamento...) e a cor que o ge usa.
    faixa: str = ""
    cor: str = ""
    variacao: int = 0


@dataclass(frozen=True)
class Tabela:
    """A classificação inteira de uma série."""

    linhas: tuple[LinhaTabela, ...]
    rodada: int | None = None
    total_rodadas: int | None = None
    # Legenda das faixas, na ordem da tabela: [{"nome": ..., "cor": ...}].
    faixas: tuple[dict, ...] = field(default_factory=tuple)

    def do_clube(self, equipe_id: int) -> LinhaTabela | None:
        """A linha do clube, se ele está nesta série."""
        return next((ln for ln in self.linhas if ln.equipe_id == equipe_id), None)


_COR = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def _cor(valor) -> str:
    """Só aceita cor hexadecimal: ela vai direto para o CSS do card."""
    return valor if isinstance(valor, str) and _COR.match(valor) else ""


def parse_classificacao(pagina: str) -> Tabela:
    """A tabela completa da página do campeonato, com pontos e forma recente."""
    dados = _json_apos(pagina, r'"classificacao"\s*:\s*\[', "[")
    if not isinstance(dados, list):
        raise SourceUnavailableError("A página do campeonato veio sem classificação.")

    faixas_brutas = _json_apos(pagina, r'"faixas_classificacao"\s*:\s*\[', "[")
    faixas = tuple(
        {"nome": f["nome"], "cor": _cor(f.get("cor"))}
        for f in faixas_brutas or []
        if isinstance(f, dict) and f.get("nome") and _cor(f.get("cor"))
    )
    nome_da_cor = {f["cor"].lower(): f["nome"] for f in faixas}

    linhas = []
    for linha in dados:
        linha = linha or {}
        equipe_id = _inteiro(linha.get("equipe_id"))
        posicao = _inteiro(linha.get("ordem"))
        nome = linha.get("nome_popular")
        if equipe_id is None or posicao is None or not nome:
            continue
        cor = _cor(
            linha.get("faixa_classificacao_cor")
            or (linha.get("faixa_classificacao") or {}).get("cor")
        )
        linhas.append(
            LinhaTabela(
                posicao=posicao,
                equipe_id=equipe_id,
                nome=nome,
                sigla=linha.get("sigla") or sigla_de(nome),
                escudo=linha.get("escudo") or "",
                pontos=_inteiro(linha.get("pontos")) or 0,
                jogos=_inteiro(linha.get("jogos")) or 0,
                vitorias=_inteiro(linha.get("vitorias")) or 0,
                empates=_inteiro(linha.get("empates")) or 0,
                derrotas=_inteiro(linha.get("derrotas")) or 0,
                gols_pro=_inteiro(linha.get("gols_pro")) or 0,
                gols_contra=_inteiro(linha.get("gols_contra")) or 0,
                saldo_gols=_inteiro(linha.get("saldo_gols")) or 0,
                aproveitamento=_inteiro(linha.get("aproveitamento")) or 0,
                ultimos_jogos=tuple(
                    r for r in linha.get("ultimos_jogos") or [] if r in ("v", "e", "d")
                ),
                faixa=nome_da_cor.get(cor.lower(), ""),
                cor=cor,
                variacao=_inteiro(linha.get("variacao")) or 0,
            )
        )
    if not linhas:
        raise SourceUnavailableError("A classificação do campeonato veio vazia.")

    rodada = _json_apos(pagina, r'"rodada"\s*:\s*\{(?=\s*"atual")', "{")
    rodada = rodada if isinstance(rodada, dict) else {}
    return Tabela(
        linhas=tuple(sorted(linhas, key=lambda ln: ln.posicao)),
        rodada=_inteiro(rodada.get("atual")),
        total_rodadas=_inteiro(rodada.get("ultima")),
        faixas=faixas,
    )


def resultado(jogo: Jogo, equipe_id: int) -> str | None:
    """"vitoria", "empate" ou "derrota" do ponto de vista do clube."""
    if jogo.placar_mandante is None or jogo.placar_visitante is None:
        return None
    if jogo.placar_mandante == jogo.placar_visitante:
        return "empate"
    mandante_venceu = jogo.placar_mandante > jogo.placar_visitante
    return "vitoria" if mandante_venceu == (jogo.mandante.id == equipe_id) else "derrota"


def parse_round(pagina: str, campeonato: str, equipe_id: int) -> list[Jogo]:
    """Jogos do clube na rodada atual da página do campeonato."""
    lista = _json_apos(pagina, r'"lista_jogos"\s*:\s*\[', "[")
    if not isinstance(lista, list):
        return []
    rodada = None
    m = re.search(r'"rodada"\s*:\s*\{\s*"atual"\s*:\s*(\d+)', pagina)
    if m:
        rodada = int(m[1])

    jogos = []
    for item in lista:
        equipes = (item or {}).get("equipes") or {}
        mandante = _equipe_sde(equipes.get("mandante"))
        visitante = _equipe_sde(equipes.get("visitante"))
        if equipe_id not in (mandante.id, visitante.id):
            continue
        quando = _quando(item.get("data_realizacao"), item.get("hora_realizacao"))
        if quando is None:
            continue
        jogos.append(
            Jogo(
                id=_inteiro(item.get("id")),
                inicio=quando[0],
                hora_definida=quando[1],
                mandante=mandante,
                visitante=visitante,
                campeonato=campeonato,
                rodada=rodada,
                estadio=(item.get("sede") or {}).get("nome_popular") or "",
                link=(item.get("transmissao") or {}).get("url") or "",
                placar_mandante=_inteiro(item.get("placar_oficial_mandante")),
                placar_visitante=_inteiro(item.get("placar_oficial_visitante")),
                situacao=_situacao_sde(item),
            )
        )
    return sorted(jogos, key=lambda j: j.inicio)


# --------------------------------------------------------------------------
# Escolha do próximo jogo
# --------------------------------------------------------------------------


def proximos(jogos: list[Jogo], agora: datetime) -> list[Jogo]:
    """Jogos ainda por vir ou em andamento, em ordem de início."""
    return sorted(
        (
            j
            for j in jogos
            # "ao vivo" vale mesmo com atraso, mas com teto: se o ge esquecer de
            # virar o status, o card não fica preso num jogo de ontem.
            if (j.situacao == "ao_vivo" and j.inicio + LIMITE_AO_VIVO > agora)
            or (j.situacao == "futuro" and j.inicio + DURACAO_JOGO > agora)
        ),
        key=lambda j: j.inicio,
    )


def proximo(jogos: list[Jogo], agora: datetime) -> Jogo | None:
    """O jogo que o card deve mostrar agora."""
    candidatos = proximos(jogos, agora)
    return candidatos[0] if candidatos else None


def sigla_de(nome: str) -> str:
    """Sigla improvisada para clubes que o ge não informa (ex.: estrangeiros)."""
    letras = re.sub(r"[^A-Z]", "", slugify(nome).upper())
    return letras[:3] or nome[:3].upper()
