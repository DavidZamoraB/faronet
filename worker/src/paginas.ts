/** Paginas HTML minimas. Todo el contenido dinamico se inserta con textContent. */

const ESTILO = `
  :root { color-scheme: light dark; --fondo:#fafaf7; --texto:#1f1f1c; --tenue:#6b6a63; --borde:#d9d7cf; --acento:#185fa5; }
  @media (prefers-color-scheme: dark) { :root { --fondo:#1b1b19; --texto:#ecebe5; --tenue:#a3a29b; --borde:#3a3a36; --acento:#85b7eb; } }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--fondo); color:var(--texto); font:16px/1.6 system-ui, sans-serif; }
  main { max-width: 720px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 22px; font-weight: 500; margin: 0 0 4px; }
  h2 { font-size: 18px; font-weight: 500; }
  p.tenue, .tenue { color: var(--tenue); font-size: 14px; }
  a { color: var(--acento); }
  ul.salas { list-style: none; padding: 0; }
  ul.salas li { padding: 8px 0; border-bottom: 1px solid var(--borde); }
  .msg { padding: 10px 0; border-bottom: 1px solid var(--borde); overflow-wrap: anywhere; }
  .msg .meta { color: var(--tenue); font-size: 13px; }
  form { display: flex; gap: 8px; margin: 16px 0; }
  input { flex: 1; padding: 8px; border: 1px solid var(--borde); border-radius: 8px; background: transparent; color: inherit; font: inherit; }
  button { padding: 8px 14px; border: 1px solid var(--borde); border-radius: 8px; background: transparent; color: inherit; font: inherit; cursor: pointer; }
`;

function pagina(titulo: string, cuerpo: string, script: string, nonce: string): string {
  return `<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${titulo}</title>
<style nonce="${nonce}">${ESTILO}</style>
</head>
<body><main>${cuerpo}</main>
<script nonce="${nonce}">${script}</script>
</body>
</html>`;
}

export function politicaContenido(nonce: string): string {
  return `default-src 'none'; script-src 'nonce-${nonce}'; style-src 'nonce-${nonce}'; connect-src 'self'; ` +
    `base-uri 'none'; form-action 'none'; frame-ancestors 'none'`;
}

export function paginaInicio(nonce: string): string {
  const cuerpo = `
  <h1>FaroNet</h1>
  <p class="tenue">Salas publicas de la red FaroNet. Los mensajes llegan desde la mesh anonima a traves de un gateway.
  Este sitio no guarda direcciones IP ni identificadores de quienes lo visitan.</p>
  <form id="ir"><input id="tema" placeholder="nombre de una sala, p. ej. general" pattern="[a-z0-9][a-z0-9-]{0,31}" required>
  <button>Abrir</button></form>
  <h2>Salas activas</h2>
  <ul class="salas" id="salas"><li class="tenue">Cargando...</li></ul>
  <p class="tenue"><a href="/api/directorio">Directorio publico de nodos (JSON, firmas verificables)</a></p>`;
  const script = `
  document.getElementById("ir").addEventListener("submit", (e) => {
    e.preventDefault();
    location.href = "/salas/" + encodeURIComponent(document.getElementById("tema").value.trim().toLowerCase());
  });
  fetch("/api/salas").then((r) => r.json()).then(({ salas }) => {
    const ul = document.getElementById("salas");
    ul.textContent = "";
    if (!salas.length) { const li = document.createElement("li"); li.className = "tenue"; li.textContent = "Todavia no hay salas."; ul.append(li); }
    for (const s of salas) {
      const li = document.createElement("li"), a = document.createElement("a");
      a.href = "/salas/" + s.tema; a.textContent = "#" + s.tema;
      const t = document.createElement("span"); t.className = "tenue"; t.textContent = "  " + new Date(s.ultimo).toLocaleString();
      li.append(a, t); ul.append(li);
    }
  });`;
  return pagina("FaroNet", cuerpo, script, nonce);
}

export function paginaSala(tema: string, nonce: string): string {
  const cuerpo = `
  <p><a href="/">&larr; FaroNet</a></p>
  <h1>#${tema}</h1>
  <p class="tenue"><span id="estado">Conectando...</span> &middot; <a href="/salas/${tema}/feed.xml">Feed Atom</a></p>
  <div id="mensajes"></div>`;
  const script = `
  const caja = document.getElementById("mensajes"), estado = document.getElementById("estado");
  function mostrar(m) {
    const d = document.createElement("div"); d.className = "msg";
    const meta = document.createElement("div"); meta.className = "meta";
    meta.textContent = (m.alias || "anonimo") + " · " + new Date(m.fecha).toLocaleString();
    const t = document.createElement("div"); t.textContent = m.texto;
    d.append(meta, t); caja.prepend(d);
  }
  function conectar() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + location.pathname + "/ws");
    ws.onopen = () => { estado.textContent = "En vivo"; };
    ws.onclose = () => { estado.textContent = "Desconectado, reintentando..."; setTimeout(conectar, 3000); };
    ws.onmessage = (e) => {
      const d = JSON.parse(e.data);
      if (d.tipo === "historial") { caja.textContent = ""; d.mensajes.forEach(mostrar); }
      if (d.tipo === "mensaje") mostrar(d.mensaje);
    };
  }
  conectar();`;
  return pagina(`FaroNet #${tema}`, cuerpo, script, nonce);
}
