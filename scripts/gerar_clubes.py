"""Gera ``custom_components/proximo_jogo/clubes.py`` a partir do ge.globo.

Rodar a cada temporada (quando mudam os clubes das Séries A e B):

    python scripts/gerar_clubes.py

O ge não tem um padrão de URL por clube (``/rs/futebol/times/gremio/``,
``/sp/tem-esporte/futebol/times/novorizontino/``...), e a agenda às vezes é
"agenda-de-jogos-da-ponte-preta". Por isso a tabela é descoberta e conferida
aqui, uma vez, e embarcada na integração.
"""

from __future__ import annotations

import importlib.util
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
COMPONENTE = RAIZ / "custom_components" / "proximo_jogo"

# Importa o parser sem passar pelo __init__ do pacote, que exige o HA.
_spec = importlib.util.spec_from_file_location("parser", COMPONENTE / "parser.py")
parser = importlib.util.module_from_spec(_spec)
sys.modules["parser"] = parser
_spec.loader.exec_module(parser)

SERIES = {
    "a": "https://ge.globo.com/futebol/brasileirao-serie-a/",
    "b": "https://ge.globo.com/futebol/brasileirao-serie-b/",
}
UFS = (
    "ac al am ap ba ce df es go ma mg ms mt pa pb pe pi pr rj rn ro rr rs sc se sp to"
).split()

# Correções manuais, se algum clube não for achado automaticamente.
URL_TIME_MANUAL: dict[str, str] = {}


def baixar(url: str) -> tuple[int, str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.geturl(), resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return err.code, url, ""
    except OSError:
        return 0, url, ""


def links_de_times(pagina: str) -> dict[str, str]:
    achados: dict[str, str] = {}
    pagina = pagina.replace("\\/", "/")
    for m in re.finditer(
        r"https://ge\.globo\.com/(?:[a-z0-9-]+/)*?futebol/times/([a-z0-9-]+)/", pagina
    ):
        achados.setdefault(m[1], m[0])
    return achados


def resolver(clube, serie: str, conhecidos: dict[str, str]) -> dict:
    slug = parser.slugify(clube.nome)
    candidatos = [URL_TIME_MANUAL.get(slug), conhecidos.get(slug)]
    candidatos += [f"https://ge.globo.com/futebol/times/{slug}/"]
    candidatos += [f"https://ge.globo.com/{uf}/futebol/times/{slug}/" for uf in UFS]

    url_time = pagina_time = None
    for url in filter(None, candidatos):
        status, final, pagina = baixar(url)
        if status == 200 and "/futebol/times/" in final:
            url_time, pagina_time = final, pagina
            break

    url_agenda = None
    if pagina_time is not None:
        tentativas = [
            parser.find_agenda_url(pagina_time),
            f"{url_time}agenda-de-jogos-do-{slug}/",
        ]
        for url in filter(None, tentativas):
            status, final, pagina = baixar(url)
            if status == 200 and parser.parse_agenda(pagina) is not None:
                url_agenda = final
                break

    tem_jogos = pagina_time is not None and parser.parse_team_page(pagina_time)
    return {
        "id": clube.id,
        "nome": clube.nome,
        "sigla": clube.sigla,
        "serie": serie,
        "time": url_time,
        "agenda": url_agenda,
        "fonte": "agenda" if url_agenda else "time" if tem_jogos else "campeonato",
    }


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    trabalhos = []
    conhecidos: dict[str, str] = {}
    for serie, url in SERIES.items():
        _, _, pagina = baixar(url)
        conhecidos.update(links_de_times(pagina))
        trabalhos += [(c, serie) for c in parser.parse_standings(pagina)]

    with ThreadPoolExecutor(8) as pool:
        clubes = list(pool.map(lambda t: resolver(t[0], t[1], conhecidos), trabalhos))

    linhas = [
        '"""Clubes das Séries A e B e as páginas de cada um no ge.globo.',
        "",
        "Gerado por scripts/gerar_clubes.py — não editar à mão.",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "from typing import Final",
        "",
        "CLUBES: Final[dict[int, dict[str, str | None]]] = {",
    ]
    for c in clubes:
        print(f"{c['serie']} {c['sigla']:4} {c['nome']:15} {c['fonte']:10} {c['time']}")
        linhas += [
            f"    {c['id']}: {{",
            f'        "nome": "{c["nome"]}",',
            f'        "sigla": "{c["sigla"]}",',
            f'        "serie": "{c["serie"]}",',
            f'        "time": {repr(c["time"])},',
            f'        "agenda": {repr(c["agenda"])},',
            "    },",
        ]
    linhas += ["}", ""]
    (COMPONENTE / "clubes.py").write_text(
        "\n".join(linhas).replace("'", '"'), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
