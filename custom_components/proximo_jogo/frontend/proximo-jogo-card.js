/*
 * Card "Próximo Jogo" — servido e carregado pela própria integração
 * (custom_components/proximo_jogo/__init__.py), sem instalação à parte.
 *
 * Lê o sensor "Próximo jogo": o estado é o horário e os atributos trazem
 * times, escudos, campeonato, estádio, transmissão e placar. Nos modos
 * "completo" e "tabela" lê também os sensores "Último resultado" e
 * "Classificação" do mesmo clube (achados pelo dispositivo).
 *
 * Modos:
 *   compacto — só o próximo jogo (o card das versões 0.1);
 *   completo — próximo jogo, último resultado e o trecho da tabela em volta
 *              do clube, com botão para abrir a tabela inteira;
 *   tabela   — só a classificação inteira, com a legenda das faixas.
 */

const CARD_VERSION = "0.2.0";
const DOMAIN = "proximo_jogo";
const MODOS = ["compacto", "completo", "tabela"];

const TEXTOS = {
  pt: {
    sem_jogo: "Sem jogo marcado",
    sem_entidade: "Escolha o sensor \"Próximo jogo\" da integração.",
    entidade_ausente: "Entidade não encontrada",
    indisponivel: "Agenda indisponível no momento",
    ao_vivo: "AO VIVO",
    hoje: "Hoje",
    amanha: "Amanhã",
    ontem: "Ontem",
    as: "às",
    a_definir: "horário a definir",
    em_casa: "Em casa",
    fora: "Fora de casa",
    rodada: "Rodada",
    de: "de",
    onde: "Onde assistir",
    ultimo: "Último jogo",
    classificacao: "Classificação",
    sem_tabela: "Tabela indisponível no momento",
    ver_tabela: "Ver tabela",
    ver_resumo: "Resumo",
    pts: "P",
    jogos: "J",
    saldo: "SG",
    forma: "Últimos",
    v: "V",
    e: "E",
    d: "D",
    vitoria: "Vitória",
    empate: "Empate",
    derrota: "Derrota",
  },
  en: {
    sem_jogo: "No match scheduled",
    sem_entidade: "Pick the \"Next match\" sensor of the integration.",
    entidade_ausente: "Entity not found",
    indisponivel: "Schedule unavailable right now",
    ao_vivo: "LIVE",
    hoje: "Today",
    amanha: "Tomorrow",
    ontem: "Yesterday",
    as: "at",
    a_definir: "time to be confirmed",
    em_casa: "Home",
    fora: "Away",
    rodada: "Round",
    de: "of",
    onde: "Where to watch",
    ultimo: "Last match",
    classificacao: "Standings",
    sem_tabela: "Standings unavailable right now",
    ver_tabela: "Full table",
    ver_resumo: "Summary",
    pts: "Pts",
    jogos: "P",
    saldo: "GD",
    forma: "Form",
    v: "W",
    e: "D",
    d: "L",
    vitoria: "Win",
    empate: "Draw",
    derrota: "Loss",
  },
};

const esc = (valor) =>
  String(valor ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );

// Escudos e links vêm do ge: só aceita https para não injetar outro esquema.
const urlSegura = (valor) => (/^https:\/\//.test(valor || "") ? valor : "");
// A cor da faixa vai direto no CSS: só hexadecimal.
const corSegura = (valor) => (/^#[0-9a-fA-F]{3,8}$/.test(valor || "") ? valor : "");
const numero = (valor) => (Number.isFinite(Number(valor)) ? Number(valor) : 0);

class ProximoJogoCard extends HTMLElement {
  static getStubConfig(hass) {
    const entity = Object.keys(hass.states).find(
      (id) =>
        id.startsWith("sensor.") &&
        hass.states[id].attributes?.device_class === "timestamp" &&
        (hass.entities?.[id]?.platform === DOMAIN || "sigla_time" in hass.states[id].attributes),
    );
    // os padrões vão explícitos para o editor visual mostrar os interruptores como estão no card
    return {
      entity: entity || "",
      modo: "completo",
      mostrar_campeonato: true,
      mostrar_transmissao: true,
      mostrar_nome: false,
    };
  }

  static getConfigForm() {
    return {
      schema: [
        {
          name: "entity",
          required: true,
          // só o sensor "Próximo jogo" de cada clube (os outros sensores não servem para o card)
          selector: { entity: { filter: { integration: DOMAIN, domain: "sensor", device_class: "timestamp" } } },
        },
        {
          name: "modo",
          selector: {
            select: {
              mode: "dropdown",
              options: [
                { value: "compacto", label: "Compacto: só o próximo jogo" },
                { value: "completo", label: "Completo: jogo, último resultado e tabela" },
                { value: "tabela", label: "Só a tabela do campeonato" },
              ],
            },
          },
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
          modo: "Tamanho do card",
          mostrar_campeonato: "Mostrar campeonato",
          mostrar_transmissao: "Mostrar onde assistir",
          mostrar_nome: "Nome do time em vez da sigla",
        })[s.name],
    };
  }

  setConfig(config) {
    if (!config) throw new Error("Configuração inválida");
    this._config = {
      // sem "modo" é o card das versões 0.1: quem já usa não vê nada mudar
      modo: "compacto",
      mostrar_campeonato: true,
      mostrar_transmissao: true,
      mostrar_nome: false,
      ...config,
    };
    if (!MODOS.includes(this._config.modo)) this._config.modo = "compacto";
    this._assinatura = null;
    this._expandida = false;
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // Só redesenha quando um dos sensores do clube muda, não a cada estado da casa.
    const ids = [this._config?.entity, ...this._irmaos()];
    const assinatura = ids
      .map((id) => {
        const s = hass.states[id];
        return s ? `${s.state}|${s.last_updated}` : "x";
      })
      .join(";");
    if (assinatura === this._assinatura) return;
    this._assinatura = assinatura;
    this._render();
  }

  getCardSize() {
    return { compacto: 3, completo: 7, tabela: 11 }[this._config?.modo] || 3;
  }

  getGridOptions() {
    if (this._config?.modo === "compacto") return { columns: 12, min_columns: 6, rows: 3, min_rows: 3 };
    // a altura acompanha o conteúdo (a tabela abre e fecha)
    return { columns: 12, min_columns: 6, rows: "auto", min_rows: 4 };
  }

  _t(chave) {
    const lingua = (this._hass?.locale?.language || this._hass?.language || "pt").slice(0, 2);
    return (TEXTOS[lingua] || TEXTOS.pt)[chave];
  }

  // ---------------------------------------------------------------- sensores

  /** IDs de "Classificação" e "Último resultado" do mesmo clube. */
  _irmaos() {
    if (!this._hass || !this._config || this._config.modo === "compacto") return [];
    return [this._idIrmao("classificacao"), this._idIrmao("ultimo_resultado")].filter(Boolean);
  }

  _idIrmao(chave) {
    const manual = this._config[`entity_${chave}`];
    if (manual) return manual;
    const reg = this._hass.entities || {};
    const dispositivo = reg[this._config.entity]?.device_id;
    if (!dispositivo) return null;
    const doClube = Object.keys(reg).filter(
      (id) => reg[id].device_id === dispositivo && reg[id].platform === DOMAIN,
    );
    // pelo translation_key; se o HA não mandar, pelo atributo que só aquele sensor tem
    return (
      doClube.find((id) => reg[id].translation_key === chave) ||
      doClube.find((id) => {
        const at = this._hass.states[id]?.attributes || {};
        return chave === "classificacao" ? Array.isArray(at.tabela) : (at.options || []).includes("vitoria");
      }) ||
      null
    );
  }

  _irmao(chave) {
    const id = this._idIrmao(chave);
    const estado = id ? this._hass.states[id] : null;
    return estado && estado.state !== "unavailable" && estado.state !== "unknown" ? estado : null;
  }

  // ------------------------------------------------------------------- datas

  _rotuloDia(data) {
    const tz = this._hass.config?.time_zone || undefined;
    const lingua = this._hass.locale?.language || "pt-BR";
    const dia = (d) => new Intl.DateTimeFormat("en-CA", { timeZone: tz, dateStyle: "short" }).format(d);
    const hoje = new Date();
    if (dia(data) === dia(hoje)) return this._t("hoje");
    if (dia(data) === dia(new Date(hoje.getTime() + 86400000))) return this._t("amanha");
    if (dia(data) === dia(new Date(hoje.getTime() - 86400000))) return this._t("ontem");
    // "qua., 04/11" -> "Qua, 04/11"
    const rotulo = new Intl.DateTimeFormat(lingua, {
      timeZone: tz,
      weekday: "short",
      day: "2-digit",
      month: "2-digit",
    })
      .format(data)
      .replace(/\.,/, ",");
    return rotulo.charAt(0).toUpperCase() + rotulo.slice(1);
  }

  _quando(estado, a) {
    const data = new Date(estado.state);
    if (Number.isNaN(data.getTime())) return "";
    const rotulo = this._rotuloDia(data);
    if (a.hora_definida === false) return `${rotulo} · ${this._t("a_definir")}`;
    const hora = new Intl.DateTimeFormat(this._hass.locale?.language || "pt-BR", {
      timeZone: this._hass.config?.time_zone || undefined,
      hour: "2-digit",
      minute: "2-digit",
    }).format(data);
    return `${rotulo} ${this._t("as")} ${hora}`;
  }

  // ------------------------------------------------------------------ partes

  _escudo(url, nome, sigla, classe) {
    const img = urlSegura(url);
    return img
      ? `<img class="${classe}" src="${esc(img)}" alt="${esc(nome)}" loading="lazy">`
      : `<span class="sem-escudo ${classe}">${esc((sigla || nome || "?").slice(0, 3))}</span>`;
  }

  _time(nome, sigla, escudo) {
    const rotulo = this._config.mostrar_nome ? nome : sigla || nome;
    return `
      <div class="time">
        ${this._escudo(escudo, nome, sigla, "grande")}
        <span class="sigla" title="${esc(nome)}">${esc(rotulo)}</span>
      </div>`;
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
    const campeonato = [a.campeonato, etapa].filter(Boolean).join(" · ");
    const topo =
      this._config.mostrar_campeonato && campeonato ? `<div class="campeonato">${esc(campeonato)}</div>` : "";
    const transmissao =
      this._config.mostrar_transmissao && (a.transmissao || []).length
        ? `<div class="transmissao" title="${this._t("onde")}">📺 ${a.transmissao.map(esc).join(" · ")}</div>`
        : "";

    return `
      <div class="bloco-jogo" data-link="${esc(urlSegura(a.link))}">
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
        ${transmissao}
      </div>`;
  }

  _ultimo() {
    const estado = this._irmao("ultimo_resultado");
    if (!estado) return "";
    const u = estado.attributes;
    const r = ["vitoria", "empate", "derrota"].includes(estado.state) ? estado.state : "";
    const data = new Date(u.data);
    const quando = Number.isNaN(data.getTime()) ? "" : this._rotuloDia(data);
    const lado = (nome, sigla, escudo) =>
      `<span class="lado">${this._escudo(escudo, nome, sigla, "mini")}<b>${esc(this._config.mostrar_nome ? nome : sigla || nome)}</b></span>`;
    return `
      <div class="ultimo" data-link="${esc(urlSegura(u.link))}">
        <span class="rotulo">${this._t("ultimo")}</span>
        ${r ? `<span class="resultado ${r}" title="${this._t(r)}">${this._t(r[0])}</span>` : ""}
        <span class="confronto">
          ${lado(u.mandante, u.sigla_mandante, u.escudo_mandante)}
          <span class="gols">${esc(u.placar_mandante)} x ${esc(u.placar_visitante)}</span>
          ${lado(u.visitante, u.sigla_visitante, u.escudo_visitante)}
        </span>
        <span class="quando">${esc(quando)}</span>
      </div>`;
  }

  _forma(ultimos) {
    return `<span class="forma">${(ultimos || [])
      .slice(-5)
      .map((r) => (["v", "e", "d"].includes(r) ? `<i class="${r}" title="${this._t(r)}"></i>` : ""))
      .join("")}</span>`;
  }

  /** A tabela inteira, ou 5 linhas em volta do clube. */
  _tabela(completa) {
    const estado = this._irmao("classificacao");
    if (!estado || !Array.isArray(estado.attributes.tabela))
      return `<div class="aviso pequeno">${this._t("sem_tabela")}</div>`;
    const t = estado.attributes;
    const linhas = t.tabela;
    let mostrar = linhas;
    if (!completa) {
      const i = Math.max(0, linhas.findIndex((ln) => ln.equipe_id === t.equipe_id));
      const inicio = Math.min(Math.max(0, i - 2), Math.max(0, linhas.length - 5));
      mostrar = linhas.slice(inicio, inicio + 5);
    }
    const rodada = t.rodada
      ? ` · ${this._t("rodada")} ${esc(t.rodada)}${t.total_rodadas ? ` ${this._t("de")} ${esc(t.total_rodadas)}` : ""}`
      : "";
    const botao =
      this._config.modo === "completo"
        ? `<button class="alternar" type="button">${this._t(completa ? "ver_resumo" : "ver_tabela")}</button>`
        : "";
    const legenda =
      completa && (t.faixas || []).length
        ? `<div class="legenda">${t.faixas
            .filter((f) => corSegura(f.cor))
            .map((f) => `<span><i style="background:${corSegura(f.cor)}"></i>${esc(f.nome)}</span>`)
            .join("")}</div>`
        : "";

    return `
      <div class="tabela">
        <div class="cabeca">
          <span>${esc(t.serie || this._t("classificacao"))}${rodada}</span>
          ${botao}
        </div>
        <table>
          <thead><tr>
            <th class="pos">#</th><th class="clube"></th>
            <th>${this._t("pts")}</th><th class="col-j">${this._t("jogos")}</th>
            <th class="col-sg">${this._t("saldo")}</th><th class="col-forma">${this._t("forma")}</th>
          </tr></thead>
          <tbody>
            ${mostrar
              .map((ln) => {
                const cor = corSegura(ln.cor);
                const sg = numero(ln.saldo_gols);
                const nome = this._config.mostrar_nome || completa ? ln.nome : ln.sigla || ln.nome;
                return `
                <tr class="${ln.equipe_id === t.equipe_id ? "meu" : ""}">
                  <td class="pos"><span class="faixa" style="${cor ? `background:${cor}` : ""}"></span>${esc(ln.posicao)}</td>
                  <td class="clube"><div>${this._escudo(ln.escudo, ln.nome, ln.sigla, "mini")}<span title="${esc(ln.nome)}">${esc(nome)}</span></div></td>
                  <td class="pts">${esc(ln.pontos)}</td>
                  <td class="col-j">${esc(ln.jogos)}</td>
                  <td class="col-sg">${sg > 0 ? "+" : ""}${sg}</td>
                  <td class="col-forma">${this._forma(ln.ultimos_jogos)}</td>
                </tr>`;
              })
              .join("")}
          </tbody>
        </table>
        ${legenda}
      </div>`;
  }

  // ------------------------------------------------------------------ render

  _render() {
    if (!this.shadowRoot || !this._config || !this._hass) return;
    const estado = this._hass.states[this._config.entity];
    const modo = this._config.modo;

    let corpo;
    if (!this._config.entity) corpo = `<div class="aviso">${this._t("sem_entidade")}</div>`;
    else if (!estado) corpo = `<div class="aviso">${this._t("entidade_ausente")}: ${esc(this._config.entity)}</div>`;
    else if (modo === "tabela") corpo = this._tabela(true);
    else {
      let jogo;
      if (estado.state === "unavailable") jogo = `<div class="aviso">${this._t("indisponivel")}</div>`;
      else if (!estado.attributes.mandante)
        jogo = `<div class="aviso">⚽ ${this._t("sem_jogo")}${estado.attributes.time ? ` · ${esc(estado.attributes.time)}` : ""}</div>`;
      else jogo = this._jogo(estado);
      corpo = modo === "completo" ? `${jogo}${this._ultimo()}${this._tabela(this._expandida)}` : jogo;
    }

    this.shadowRoot.innerHTML = `<style>${ESTILO}</style><ha-card class="${modo}">${corpo}</ha-card>`;
    const card = this.shadowRoot.querySelector("ha-card");

    if (modo === "compacto") {
      // o card inteiro é o jogo: abre a página da partida (ou o mais-info, sem link)
      const link = urlSegura(estado?.attributes?.link);
      card.onclick = () => {
        if (link) window.open(link, "_blank", "noopener");
        else if (estado) this._maisInfo(this._config.entity);
      };
      return;
    }
    card.querySelectorAll("[data-link]").forEach((el) => {
      el.classList.add("clicavel");
      el.onclick = () => {
        if (el.dataset.link) window.open(el.dataset.link, "_blank", "noopener");
        else this._maisInfo(el.classList.contains("ultimo") ? this._idIrmao("ultimo_resultado") : this._config.entity);
      };
    });
    const botao = card.querySelector(".alternar");
    if (botao)
      botao.onclick = (ev) => {
        ev.stopPropagation();
        this._expandida = !this._expandida;
        this._render();
      };
  }

  _maisInfo(entityId) {
    if (!entityId) return;
    const ev = new Event("hass-more-info", { bubbles: true, composed: true });
    ev.detail = { entityId };
    this.dispatchEvent(ev);
  }
}

const ESTILO = `
  ha-card { padding: 12px 16px 14px; height: 100%; box-sizing: border-box;
    display: flex; flex-direction: column; justify-content: center; gap: 10px;
    container-type: inline-size; }
  ha-card.compacto { cursor: pointer; gap: 6px; }
  ha-card.completo, ha-card.tabela { justify-content: flex-start; }
  .clicavel { cursor: pointer; border-radius: 12px; }
  .clicavel:hover { background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); }
  .bloco-jogo { display: flex; flex-direction: column; gap: 6px; padding: 2px 0; }

  .campeonato { text-align: center; font-size: 12px; color: var(--secondary-text-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .jogo { display: grid; grid-template-columns: 1fr 1.4fr 1fr; align-items: center; gap: 8px; }
  .time { display: flex; flex-direction: column; align-items: center; gap: 6px; min-width: 0; }
  img.grande, .sem-escudo.grande { width: 64px; height: 64px; object-fit: contain; }
  img.mini, .sem-escudo.mini { width: 20px; height: 20px; object-fit: contain; flex: none; }
  .sem-escudo { border-radius: 50%; display: inline-grid; place-items: center;
    background: var(--secondary-background-color); font-weight: 700; font-size: 9px; }
  .sem-escudo.grande { font-size: 16px; }
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
  .aviso.pequeno { padding: 8px 0; font-size: 13px; }

  /* último resultado */
  .ultimo { display: flex; align-items: center; gap: 8px; padding: 8px 10px; font-size: 13px;
    background: color-mix(in srgb, var(--primary-text-color) 4%, transparent); }
  .ultimo .rotulo { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; }
  .resultado { flex: none; width: 22px; height: 22px; border-radius: 6px; display: grid; place-items: center;
    font-size: 11px; font-weight: 800; color: #fff; }
  .resultado.vitoria, .forma i.v { background: var(--success-color, #2e9e4f); }
  .resultado.empate, .forma i.e { background: var(--disabled-color, #8a8f98); }
  .resultado.derrota, .forma i.d { background: var(--error-color, #db4437); }
  .confronto { display: flex; align-items: center; gap: 6px; min-width: 0; flex: 1; justify-content: center; }
  .lado { display: inline-flex; align-items: center; gap: 4px; min-width: 0; }
  .lado b { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .gols { font-weight: 800; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .quando { color: var(--secondary-text-color); font-size: 12px; white-space: nowrap; }

  /* tabela */
  .tabela { display: flex; flex-direction: column; gap: 4px; }
  .cabeca { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 26px;
    font-size: 12px; font-weight: 600; color: var(--secondary-text-color);
    text-transform: uppercase; letter-spacing: .4px; }
  .alternar { font: inherit; text-transform: none; letter-spacing: 0; font-size: 12px; font-weight: 600;
    color: var(--primary-color); background: color-mix(in srgb, var(--primary-color) 12%, transparent);
    border: 0; border-radius: 999px; padding: 4px 12px; cursor: pointer; }
  .alternar:hover { background: color-mix(in srgb, var(--primary-color) 22%, transparent); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
  th { font-size: 11px; font-weight: 600; color: var(--secondary-text-color); text-align: center; padding: 2px 5px; }
  td { padding: 5px; text-align: center; border-top: 1px solid var(--divider-color); white-space: nowrap; }
  th.pos, td.pos { width: 24px; text-align: left; position: relative; padding-left: 9px; }
  .faixa { position: absolute; left: 0; top: 6px; bottom: 6px; width: 3px; border-radius: 2px; }
  td.clube { text-align: left; width: 100%; max-width: 0; }
  td.clube div { display: flex; align-items: center; gap: 8px; min-width: 0; }
  td.clube span { overflow: hidden; text-overflow: ellipsis; }
  td.pts { font-weight: 800; }
  tr.meu td { background: color-mix(in srgb, var(--primary-color) 15%, transparent); font-weight: 700; }
  .forma { display: inline-flex; gap: 3px; vertical-align: middle; }
  .forma i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .legenda { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 11px; color: var(--secondary-text-color);
    padding-top: 6px; }
  .legenda span { display: inline-flex; align-items: center; gap: 5px; }
  .legenda i { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }

  /* card estreito: some o que é detalhe */
  @container (max-width: 340px) {
    .col-j, .col-sg { display: none; }
    .ultimo .quando { display: none; }
  }
  @container (max-width: 300px) {
    .col-forma { display: none; }
  }
`;

if (!customElements.get("proximo-jogo-card")) {
  customElements.define("proximo-jogo-card", ProximoJogoCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "proximo-jogo-card",
    name: "Próximo Jogo",
    description: "Próximo jogo do seu clube, último resultado e a tabela do campeonato, com escudos e onde assistir.",
    preview: true,
    documentationURL: "https://github.com/dougbaptista/ha_proximo_jogo",
  });
  console.info(`%c PROXIMO-JOGO-CARD %c ${CARD_VERSION} `, "background:#0b7a3e;color:#fff", "");
}
