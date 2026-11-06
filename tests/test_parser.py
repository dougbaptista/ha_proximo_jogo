"""Testes da leitura das páginas do ge.globo, sobre recortes reais."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.proximo_jogo.parser import (
    BRT,
    Equipe,
    Jogo,
    SourceUnavailableError,
    find_agenda_url,
    parse_agenda,
    parse_agenda_passados,
    parse_classificacao,
    parse_match_venue,
    parse_round,
    parse_standings,
    parse_team_page,
    proximo,
    proximos,
    resultado,
    sigla_de,
    slugify,
)


def test_agenda_traz_estadio_rodada_e_onde_assistir(agenda_vasco: str) -> None:
    jogos = parse_agenda(agenda_vasco)
    assert [j.inicio for j in jogos] == sorted(j.inicio for j in jogos)

    primeiro = jogos[0]
    assert primeiro.inicio == datetime(2026, 11, 4, 19, 30, tzinfo=BRT)
    assert primeiro.mandante.nome == "Athletico-PR"
    assert primeiro.visitante == Equipe(
        id=267,
        nome="Vasco",
        escudo="https://s.sde.globo.com/media/organizations/2021/09/04/vasco_SVG.svg",
    )
    assert primeiro.estadio == "Arena da Baixada"
    assert primeiro.rodada == 34
    assert primeiro.campeonato == "Campeonato Brasileiro"
    assert "Premiere" in primeiro.transmissao
    assert primeiro.link.endswith("/04-11-2026/atletico-pr-vasco.ghtml")
    assert primeiro.situacao == "futuro"


def test_agenda_cobre_outros_campeonatos(agenda_vasco: str) -> None:
    campeonatos = {j.campeonato for j in parse_agenda(agenda_vasco)}
    assert "Copa do Brasil" in campeonatos


def test_agenda_ausente_devolve_none() -> None:
    assert parse_agenda("<html>sem agenda</html>") is None


def test_agenda_sem_jogos_devolve_lista_vazia() -> None:
    pagina = (
        "<script>window.dataSportsSchedule = {scheduleTeam: "
        '{"teamAgenda":{"future":[],"now":[],"past":[]}}};</script>'
    )
    assert parse_agenda(pagina) == []


def test_agenda_marca_jogo_ao_vivo_com_placar(agenda_vasco: str) -> None:
    pagina = agenda_vasco.replace('"moment":"FUTURE"', '"moment":"NOW"', 1).replace(
        '"home":null', '"home":2', 1
    )
    jogo = parse_agenda(pagina)[0]
    assert jogo.situacao == "ao_vivo"
    assert jogo.placar_mandante == 2


def test_link_da_agenda_na_pagina_do_time(time_gremio: str) -> None:
    assert find_agenda_url(time_gremio) == (
        "https://ge.globo.com/rs/futebol/times/gremio/agenda-de-jogos-do-gremio/"
    )


def test_link_da_agenda_aceita_artigo_feminino() -> None:
    pagina = (
        'href="https:\\/\\/ge.globo.com\\/sp\\/campinas-e-regiao\\/futebol\\/'
        'times\\/ponte-preta\\/agenda-de-jogos-da-ponte-preta\\/"'
    )
    assert find_agenda_url(pagina).endswith("/agenda-de-jogos-da-ponte-preta/")


def test_pagina_do_time(time_gremio: str) -> None:
    jogos = parse_team_page(time_gremio)
    assert [(j.mandante.sigla, j.visitante.sigla) for j in jogos] == [
        ("FLA", "GRE"),
        ("CAM", "GRE"),
        ("GRE", "BAH"),
    ]
    primeiro = jogos[0]
    assert primeiro.inicio == datetime(2026, 11, 4, 19, 30, tzinfo=BRT)
    assert primeiro.mandante.escudo.endswith(".svg")
    assert primeiro.estadio == ""  # vem da página da partida
    assert primeiro.link.endswith("flamengo-gremio.ghtml")
    assert jogos[1].campeonato == "Copa do Brasil"


def test_pagina_do_time_sem_jogos_devolve_none() -> None:
    assert parse_team_page("<html>só notícias</html>") is None


def test_estadio_na_pagina_da_partida(partida: str) -> None:
    assert parse_match_venue(partida) == "Maracanã"
    assert parse_match_venue("<html></html>") == ""


def test_classificacao(serie_a: str) -> None:
    clubes = parse_standings(serie_a)
    assert len(clubes) == 20
    assert (clubes[0].id, clubes[0].nome, clubes[0].sigla) == (262, "Flamengo", "FLA")
    assert {c.posicao for c in clubes} == set(range(1, 21))


def test_classificacao_ausente() -> None:
    with pytest.raises(SourceUnavailableError):
        parse_standings("<html></html>")


def test_rodada_do_campeonato_para_clube_sem_agenda(serie_a: str) -> None:
    jogos = parse_round(serie_a, "Campeonato Brasileiro", 364)
    assert len(jogos) == 1
    jogo = jogos[0]
    assert (jogo.mandante.nome, jogo.visitante.nome) == ("Palmeiras", "Remo")
    assert jogo.estadio == "Nubank Parque"
    assert jogo.rodada == 34
    assert jogo.campeonato == "Campeonato Brasileiro"


def test_rodada_sem_o_clube(serie_a: str) -> None:
    assert parse_round(serie_a, "Campeonato Brasileiro", 999999) == []


def _jogo(inicio: datetime, situacao: str = "futuro") -> Jogo:
    return Jogo(
        id=1,
        inicio=inicio,
        mandante=Equipe(id=1, nome="A"),
        visitante=Equipe(id=2, nome="B"),
        situacao=situacao,
    )


AGORA = datetime(2026, 11, 4, 20, 0, tzinfo=BRT)


def test_proximo_mantem_jogo_em_andamento() -> None:
    em_andamento = _jogo(AGORA - timedelta(minutes=30))
    seguinte = _jogo(AGORA + timedelta(days=3))
    assert proximo([seguinte, em_andamento], AGORA) is em_andamento


def test_proximo_pula_jogo_encerrado_e_vencido() -> None:
    encerrado = _jogo(AGORA - timedelta(minutes=30), "encerrado")
    antigo = _jogo(AGORA - timedelta(hours=3))
    seguinte = _jogo(AGORA + timedelta(days=3))
    assert proximo([encerrado, antigo, seguinte], AGORA) is seguinte


def test_ao_vivo_tem_teto() -> None:
    """Se o ge não virar o status, o card não fica preso no jogo de ontem."""
    esquecido = _jogo(AGORA - timedelta(hours=20), "ao_vivo")
    atrasado = _jogo(AGORA - timedelta(hours=3), "ao_vivo")
    assert proximos([esquecido, atrasado], AGORA) == [atrasado]


def test_proximo_sem_jogos() -> None:
    assert proximo([], AGORA) is None


def test_jogo_sem_hora_definida(agenda_vasco: str) -> None:
    pagina = agenda_vasco.replace('"startHour":"19:30:00"', '"startHour":null', 1)
    jogo = parse_agenda(pagina)[0]
    assert jogo.hora_definida is False
    assert jogo.inicio == datetime(2026, 11, 4, 0, 0, tzinfo=BRT)


def test_com_estadio_nao_altera_original() -> None:
    jogo = _jogo(AGORA)
    assert jogo.com_estadio("Arena").estadio == "Arena"
    assert jogo.estadio == ""
    assert replace(jogo, estadio="X") != jogo


@pytest.mark.parametrize(
    ("nome", "slug"),
    [("São Paulo", "sao-paulo"), ("Atlético-MG", "atletico-mg"), ("Grêmio", "gremio")],
)
def test_slugify(nome: str, slug: str) -> None:
    assert slugify(nome) == slug


def test_sigla_de_clube_sem_sigla() -> None:
    assert sigla_de("Peñarol") == "PEN"


def test_tabela_completa(serie_a: str) -> None:
    tabela = parse_classificacao(serie_a)
    assert len(tabela.linhas) == 20
    assert [ln.posicao for ln in tabela.linhas] == list(range(1, 21))
    assert (tabela.rodada, tabela.total_rodadas) == (34, 38)

    lider = tabela.linhas[0]
    assert (lider.equipe_id, lider.sigla) == (262, "FLA")
    assert lider.pontos == lider.vitorias * 3 + lider.empates
    assert lider.saldo_gols == lider.gols_pro - lider.gols_contra
    assert len(lider.ultimos_jogos) == 5 and set(lider.ultimos_jogos) <= {"v", "e", "d"}
    assert (lider.faixa, lider.cor) == ("Libertadores", "#0000ff")
    assert tabela.linhas[-1].faixa == "Rebaixados"
    assert [f["nome"] for f in tabela.faixas][0] == "Libertadores"
    assert tabela.do_clube(262) is lider
    assert tabela.do_clube(999999) is None


def test_tabela_recusa_cor_que_nao_e_hexadecimal(serie_a: str) -> None:
    pagina = serie_a.replace(
        '"faixa_classificacao_cor":"#0000ff"', '"faixa_classificacao_cor":"red;x"', 1
    )
    pagina = pagina.replace(
        '"faixa_classificacao":{"cor":"#0000ff"}', '"faixa_classificacao":{}', 1
    )
    assert parse_classificacao(pagina).linhas[0].cor == ""


def test_tabela_ausente() -> None:
    with pytest.raises(SourceUnavailableError):
        parse_classificacao("<html></html>")


def test_agenda_traz_o_ultimo_jogo_encerrado(agenda_vasco: str) -> None:
    passados = parse_agenda_passados(agenda_vasco)
    assert passados, "o recorte da agenda tem jogos passados"
    assert [j.inicio for j in passados] == sorted(j.inicio for j in passados)
    ultimo = passados[-1]
    assert ultimo.situacao == "encerrado"
    assert ultimo.placar_mandante is not None and ultimo.placar_visitante is not None
    assert parse_agenda_passados("<html></html>") == []


@pytest.mark.parametrize(
    ("gols_m", "gols_v", "equipe", "esperado"),
    [
        (3, 1, 1, "vitoria"),
        (3, 1, 2, "derrota"),
        (0, 2, 2, "vitoria"),
        (1, 1, 1, "empate"),
    ],
)
def test_resultado_do_ponto_de_vista_do_clube(gols_m, gols_v, equipe, esperado) -> None:
    jogo = replace(
        _jogo(AGORA, "encerrado"), placar_mandante=gols_m, placar_visitante=gols_v
    )
    assert resultado(jogo, equipe) == esperado


def test_resultado_sem_placar() -> None:
    assert resultado(_jogo(AGORA), 1) is None
