/*
 * Card "Próximo Jogo" — servido e carregado pela própria integração
 * (custom_components/proximo_jogo/__init__.py), sem instalação à parte.
 *
 * Lê o sensor "Próximo jogo": o estado é o horário e os atributos trazem
 * times, escudos, campeonato, estádio, transmissão e placar.
 */

const CARD_VERSION = "0.1.1";
const DOMAIN = "proximo_jogo";

const TEXTOS = {
  pt: {
    sem_jogo: "Sem jogo marcado",
    sem_entidade: "Escolha o sensor \"Próximo jogo\" da integração.",
    entidade_ausente: "Entidade não encontrada",
    indisponivel: "Agenda indisponível no momento",
    ao_vivo: "AO VIVO",
    hoje: "Hoje",
    amanha: "Amanhã",
    as: "às",
    a_definir: "horário a definir",
    em_casa: "Em casa",
    fora: "Fora de casa",
    rodada: "Rodada",
    onde: "Onde assistir",
  },
  en: {
    sem_jogo: "No match scheduled",
    sem_entidade: "Pick the \"Next match\" sensor of the integration.",
    entidade_ausente: "Entity not found",
    indisponivel: "Schedule unavailable right now",
    ao_vivo: "LIVE",
    hoje: "Today",
    amanha: "Tomorrow",
    as: "at",
    a_definir: "time to be confirmed",
    em_casa: "Home",
    fora: "Away",
    rodada: "Round",
    onde: "Where to watch",
  },
};

const esc = (valor) =>
  String(valor ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

// Escudos e links vêm do ge: só aceita https para não injetar outro esquema.
const urlSegura = (valor) => (/^https:\/\//.test(valor || "") ? valor : "");

class ProximoJogoCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) =>
        id.startsWith("sensor.") &&
        (hass.entities?.[id]?.platform === DOMAIN ||
          "sigla_time" in (hass.states[id].attributes || {})),
    );
    // os padrões vão explícitos para o editor visual mostrar os interruptores como estão no card
    return { entity: entity || "", mostrar_campeonato: true, mostrar_transmissao: true, mostrar_nome: false };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          selector: { entity: { filter: { integration: DOMAIN, domain: "sensor" } } },
        },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "mostrar_campeonato", selector: { boolean: {} } },
            { name: "mostrar_transmissao", selector: { boolean: {} } },
            { name: "mostrar_nome", selector: { boolean: {} } },
          ],
        },
      ],
      computeLabel: (s) =>
        ({
          entity: "Sensor \"Próximo jogo\"",
          mostrar_campeonato: "Mostrar campeonato",
          mostrar_transmissao: "Mostrar onde assistir",
          mostrar_nome: "Nome do time em vez da sigla",
        })[s.name],
    };
  }

  setConfig(config) {
    if (!config) throw new Error("Configuração inválida");
    this._config = {
      mostrar_campeonato: true,
      mostrar_transmissao: true,
      mostrar_nome: false,
      ...config,
    };
    this._assinatura = null;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Só redesenha quando o sensor muda, não a cada estado da casa.
    const estado = hass.states[this._config?.entity];
    const assinatura = estado ? `${estado.state}|${estado.last_updated}` : "x";
    if (assinatura === this._assinatura) return;
    this._assinatura = assinatura;
    this._render();
  }

  getCardSize() {
    return 3;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 3, min_rows: 3 };
  }

  _t(chave) {
    const lingua = (this._hass?.locale?.language || this._hass?.language || "pt")
      .slice(0, 2);
    return (TEXTOS[lingua] || TEXTOS.pt)[chave];
  }

  _quando(estado, a) {
    const data = new Date(estado.state);
    if (Number.isNaN(data.getTime())) return "";
    const tz = this._hass.config?.time_zone || undefined;
    const lingua = this._hass.locale?.language || "pt-BR";
    const dia = (d) =>
      new Intl.DateTimeFormat("en-CA", { timeZone: tz, dateStyle: "short" }).format(d);
    const hoje = new Date();
    const amanha = new Date(hoje.getTime() + 86400000);

    let rotulo;
    if (dia(data) === dia(hoje)) rotulo = this._t("hoje");
    else if (dia(data) === dia(amanha)) rotulo = this._t("amanha");
    else {
      rotulo = new Intl.DateTimeFormat(lingua, {
        timeZone: tz,
        weekday: "short",
        day: "2-digit",
        month: "2-digit",
      }).format(data);
      // "qua., 04/11" -> "Qua, 04/11"
      rotulo = rotulo.replace(/\.,/, ",");
      rotulo = rotulo.charAt(0).toUpperCase() + rotulo.slice(1);
    }
    if (a.hora_definida === false) return `${rotulo} · ${this._t("a_definir")}`;
    const hora = new Intl.DateTimeFormat(lingua, {
      timeZone: tz,
      hour: "2-digit",
      minute: "2-digit",
    }).format(data);
    return `${rotulo} ${this._t("as")} ${hora}`;
  }

  _time(nome, sigla, escudo) {
    const rotulo = this._config.mostrar_nome ? nome : sigla || nome;
    const img = urlSegura(escudo);
    return `
      <div class="time">
        ${img ? `<img src="${esc(img)}" alt="${esc(nome)}" loading="lazy">` : `<div class="sem-escudo">${esc((sigla || nome).slice(0, 3))}</div>`}
        <span class="sigla" title="${esc(nome)}">${esc(rotulo)}</span>
      </div>`;
  }

  _render() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    const estado = this._hass.states[this._config.entity];

    let corpo;
    if (!this._config.entity) corpo = `<div class="aviso">${this._t("sem_entidade")}</div>`;
    else if (!estado)
      corpo = `<div class="aviso">${this._t("entidade_ausente")}: ${esc(this._config.entity)}</div>`;
    else if (estado.state === "unavailable")
      corpo = `<div class="aviso">${this._t("indisponivel")}</div>`;
    else if (!estado.attributes.mandante)
      corpo = `<div class="aviso">⚽ ${this._t("sem_jogo")}${estado.attributes.time ? ` · ${esc(estado.attributes.time)}` : ""}</div>`;
    else corpo = this._jogo(estado);

    this.shadowRoot.innerHTML = `<style>${ESTILO}</style><ha-card>${corpo}</ha-card>`;
    const link = urlSegura(estado?.attributes?.link);
    this.shadowRoot.querySelector("ha-card").onclick = () => {
      if (link) window.open(link, "_blank", "noopener");
      else if (estado) this._maisInfo();
    };
  }

  _maisInfo() {
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId: this._config.entity };
    this.dispatchEvent(ev);
  }

  _jogo(estado) {
    const a = estado.attributes;
    const aoVivo = a.situacao === "ao_vivo";
    const placar =
      aoVivo && a.placar_mandante != null && a.placar_visitante != null
        ? `<div class="placar">${esc(a.placar_mandante)} <span>x</span> ${esc(a.placar_visitante)}</div>`
        : `<div class="x">X</div>`;
    const local = a.estadio || (a.mando === "casa" ? this._t("em_casa") : this._t("fora"));

    // copas não têm rodada: no lugar dela vai a fase ("Semifinal"); a "Fase única" dos pontos corridos não diz nada
    const etapa = a.rodada ? `${this._t("rodada")} ${a.rodada}` : a.fase && !/fase única/i.test(a.fase) ? a.fase : "";
    const campeonato = [a.campeonato, etapa]
      .filter(Boolean)
      .join(" · ");
    const topo =
      this._config.mostrar_campeonato && campeonato
        ? `<div class="campeonato">${esc(campeonato)}</div>`
        : "";
    const transmissao =
      this._config.mostrar_transmissao && (a.transmissao || []).length
        ? `<div class="transmissao" title="${this._t("onde")}">📺 ${a.transmissao.map(esc).join(" · ")}</div>`
        : "";

    return `
      ${topo}
      <div class="jogo">
        ${this._time(a.mandante, a.sigla_mandante, a.escudo_mandante)}
        <div class="centro">
          ${aoVivo ? `<div class="ao-vivo">${this._t("ao_vivo")}</div>` : `<div class="data">${esc(this._quando(estado, a))}</div>`}
          <div class="local">${esc(local)}</div>
          ${placar}
        </div>
        ${this._time(a.visitante, a.sigla_visitante, a.escudo_visitante)}
      </div>
      ${transmissao}`;
  }
}

const ESTILO = `
  ha-card { padding: 12px 16px 14px; cursor: pointer; height: 100%; box-sizing: border-box;
    display: flex; flex-direction: column; justify-content: center; gap: 6px; }
  .campeonato { text-align: center; font-size: 12px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .jogo { display: grid; grid-template-columns: 1fr 1.4fr 1fr; align-items: center; gap: 8px; }
  .time { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; }
  .time img { width: 64px; height: 64px; object-fit: contain; }
  .sem-escudo { width: 64px; height: 64px; border-radius: 50%; display: grid; place-items: center;
    background: var(--secondary-background-color); font-weight: 700; }
  .sigla { font-size: 15px; font-weight: 500; max-width: 100%; white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .centro { text-align: center; display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .data { font-weight: 600; font-size: 13px; }
  .local { font-size: 12px; color: var(--secondary-text-color); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .x { font-size: 22px; font-weight: 700; margin-top: 2px; }
  .placar { font-size: 26px; font-weight: 700; }
  .placar span { font-size: 16px; color: var(--secondary-text-color); }
  .ao-vivo { align-self: center; background: var(--error-color, #db4437); color: #fff;
    font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 10px; letter-spacing: .5px; }
  .transmissao { text-align: center; font-size: 12px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .aviso { text-align: center; padding: 16px 0; color: var(--secondary-text-color); }
`;

if (!customElements.get("proximo-jogo-card")) {
  customElements.define("proximo-jogo-card", ProximoJogoCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "proximo-jogo-card",
    name: "Próximo Jogo",
    description: "Próximo jogo do seu clube, com escudos, data, estádio e onde assistir.",
    preview: true,
    documentationURL: "https://github.com/dougbaptista/ha_proximo_jogo",
  });
  console.info(`%c PROXIMO-JOGO-CARD %c ${CARD_VERSION} `, "background:#0b7a3e;color:#fff", "");
}
