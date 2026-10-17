/**
 * FaroNet en el edge (Cloudflare Workers).
 *
 *   GET  /                          pagina de inicio con las salas activas
 *   GET  /salas/:tema               sala publica en vivo (navegador)
 *   GET  /salas/:tema/ws            WebSocket de la sala
 *   GET  /salas/:tema/feed.xml      feed Atom de la sala
 *   GET  /salas/:tema/mensajes      mensajes recientes (JSON)
 *   GET  /api/salas                 salas activas (JSON)
 *   GET  /api/directorio            replica publica del directorio de nodos
 *   PUT  /api/buzon/:id             deposita un blob cifrado (BLOB bytes)
 *   GET  /api/buzon/:id             retira (y borra) el blob
 *   POST /api/gateway/publicar      el gateway publica en una sala   (firmado)
 *   POST /api/gateway/directorio    el gateway sube entradas         (firmado)
 *   GET  /api/salud                 estado
 *
 * Politica de no registro: el codigo nunca guarda ni escribe en logs la IP
 * (CF-Connecting-IP), el User-Agent ni otras cabeceras del visitante. La IP
 * solo se usa, hasheada con la fecha y en memoria, para el limite de
 * peticiones.
 */
import { Buzon, BLOB, TTL_DEFECTO_S, TTL_MAXIMO_S } from "./buzon";
import { Central } from "./central";
import { paginaInicio, paginaSala, politicaContenido } from "./paginas";
import { Sala, feedAtom, MAX_ALIAS, MAX_TEXTO } from "./sala";
import { autenticarGateway, permitir } from "./seguridad";
import { deB64, Env, error, json, leerCuerpo, respuesta, TEMA } from "./util";

export { Buzon, Central, Sala };

const MAX_CUERPO_GATEWAY = 64 * 1024;
const MAX_ENTRADAS = 200;

function html(contenido: (nonce: string) => string): Response {
  const nonce = crypto.randomUUID().replace(/-/g, "");
  return respuesta(contenido(nonce), "text/html; charset=utf-8", {
    "content-security-policy": politicaContenido(nonce),
  });
}

async function publicar(req: Request, env: Env): Promise<Response> {
  const cuerpo = await leerCuerpo(req, MAX_CUERPO_GATEWAY);
  if (!cuerpo) return error(413, "cuerpo demasiado grande");
  const auth = await autenticarGateway(req, cuerpo, env);
  if (!auth.ok) return error(401, auth.motivo);
  let datos: { tema?: unknown; texto?: unknown; alias?: unknown };
  try {
    datos = JSON.parse(new TextDecoder().decode(cuerpo));
  } catch {
    return error(400, "JSON invalido");
  }
  const { tema, texto, alias = "" } = datos;
  if (typeof tema !== "string" || !TEMA.test(tema)) return error(400, "tema invalido");
  if (typeof texto !== "string" || !texto.trim() || texto.length > MAX_TEXTO) return error(400, "texto invalido");
  if (typeof alias !== "string" || alias.length > MAX_ALIAS) return error(400, "alias invalido");
  const mensaje = await env.SALAS.getByName(tema).publicar(alias, texto);
  await env.CENTRAL.getByName("central").tocarTema(tema);
  return json({ ok: true, id: mensaje.id }, 201);
}

async function subirDirectorio(req: Request, env: Env): Promise<Response> {
  const cuerpo = await leerCuerpo(req, MAX_CUERPO_GATEWAY);
  if (!cuerpo) return error(413, "cuerpo demasiado grande");
  const auth = await autenticarGateway(req, cuerpo, env);
  if (!auth.ok) return error(401, auth.motivo);
  let lista: unknown;
  try {
    lista = JSON.parse(new TextDecoder().decode(cuerpo)).entradas;
  } catch {
    return error(400, "JSON invalido");
  }
  if (!Array.isArray(lista) || lista.length > MAX_ENTRADAS) return error(400, "se esperaba {entradas: [...]}");
  const entradas = lista.map((e) => (typeof e === "string" ? deB64(e) : null)).filter((e): e is Uint8Array => !!e);
  const resultado = await env.CENTRAL.getByName("central").guardarEntradas(entradas);
  return json({ ok: true, ...resultado, rechazadas: lista.length - resultado.aceptadas });
}

async function buzon(req: Request, env: Env, id: string): Promise<Response> {
  if (!/^[0-9a-f]{64}$/.test(id)) return error(400, "el identificador son 32 bytes en hex");
  const objeto = env.BUZON.getByName("buzon");
  if (req.method === "PUT") {
    const datos = await leerCuerpo(req, BLOB);
    if (!datos || datos.length !== BLOB) return error(400, `el blob debe medir exactamente ${BLOB} bytes`);
    const ttl = Number(new URL(req.url).searchParams.get("ttl") ?? TTL_DEFECTO_S);
    if (!Number.isInteger(ttl) || ttl < 60 || ttl > TTL_MAXIMO_S) return error(400, "ttl invalido");
    const r = await objeto.depositar(id, datos, ttl);
    if (r === "ocupado") return error(409, "ese buzon ya tiene un blob");
    if (r === "lleno") return error(507, "buzon lleno, intente mas tarde");
    return json({ ok: true, ttl }, 201);
  }
  if (req.method === "GET") {
    const datos = await objeto.retirar(id);
    if (!datos) return error(404, "no hay blob (nunca existio, vencio o ya se leyo)");
    return respuesta(datos, "application/octet-stream");
  }
  return error(405, "metodo no permitido");
}

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const url = new URL(req.url);
    const partes = url.pathname.split("/").filter(Boolean);
    const esGateway = partes[0] === "api" && partes[1] === "gateway";
    if (!esGateway && !(await permitir(req, env, partes[0] ?? "inicio"))) {
      return error(429, "demasiadas peticiones");
    }

    if (req.method === "GET" && partes.length === 0) return html(paginaInicio);

    if (partes[0] === "salas" && partes[1]) {
      const tema = partes[1];
      if (!TEMA.test(tema)) return error(404, "sala invalida");
      const sala = env.SALAS.getByName(tema);
      if (partes.length === 2 && req.method === "GET") return html((n) => paginaSala(tema, n));
      if (partes[2] === "ws") return sala.fetch(req);
      if (partes[2] === "mensajes") return json({ tema, mensajes: await sala.recientes() });
      if (partes[2] === "feed.xml") {
        return respuesta(feedAtom(url.origin, tema, await sala.recientes()), "application/atom+xml; charset=utf-8");
      }
    }

    if (partes[0] === "api") {
      const central = env.CENTRAL.getByName("central");
      const ruta = partes.slice(1).join("/");
      if (req.method === "GET" && ruta === "salud") return json({ ok: true });
      if (req.method === "GET" && ruta === "salas") return json({ salas: await central.temas() });
      if (req.method === "GET" && ruta === "directorio") return json({ entradas: await central.directorio() });
      if (partes[1] === "buzon" && partes[2] && partes.length === 3) return buzon(req, env, partes[2]);
      if (req.method === "POST" && ruta === "gateway/publicar") return publicar(req, env);
      if (req.method === "POST" && ruta === "gateway/directorio") return subirDirectorio(req, env);
    }
    return error(404, "no encontrado");
  },
} satisfies ExportedHandler<Env>;
