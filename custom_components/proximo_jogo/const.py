"""Constantes da integração Próximo Jogo."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "proximo_jogo"
PLATFORMS: Final = ["sensor", "calendar"]

# Mantida igual à "version" do manifest (há teste): vai na URL do card para o
# navegador não usar o JS antigo do cache depois de uma atualização.
VERSION: Final = "0.1.1"

CONF_SERIE: Final = "serie"
CONF_EQUIPE_ID: Final = "equipe_id"
CONF_NOME: Final = "nome"
CONF_SIGLA: Final = "sigla"

SERIES: Final = {
    "a": {
        "nome": "Série A",
        "campeonato": "Campeonato Brasileiro",
        "url": "https://ge.globo.com/futebol/brasileirao-serie-a/",
    },
    "b": {
        "nome": "Série B",
        "campeonato": "Campeonato Brasileiro - Série B",
        "url": "https://ge.globo.com/futebol/brasileirao-serie-b/",
    },
}
DEFAULT_SERIE: Final = "a"

# Agenda muda pouco; perto do jogo e durante ele o placar justifica mais
# atualizações.
UPDATE_INTERVAL: Final = timedelta(hours=1)
UPDATE_INTERVAL_JOGO: Final = timedelta(minutes=5)
JANELA_JOGO: Final = timedelta(hours=1)

REQUEST_TIMEOUT: Final = 30
# As páginas do ge têm ~1 MB; o teto só barra uma resposta anômala.
MAX_PAGE_BYTES: Final = 8 * 1024 * 1024
ALLOWED_HOST: Final = "ge.globo.com"

USER_AGENT: Final = "Mozilla/5.0 (HomeAssistant; proximo_jogo)"

CARD_URL: Final = f"/{DOMAIN}/proximo-jogo-card.js"
