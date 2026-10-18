/**
 * Una sala publica por tema (un Durable Object por nombre de tema).
 *
 * Los navegadores se conectan por WebSocket (API de hibernacion: el objeto
 * se puede dormir sin cortar las conexiones) y reciben el historial reciente
 * y cada mensaje nuevo. Las salas son de solo lectura desde clearnet: solo
 * el gateway publica, con peticiones firmadas.
 *
 * Los mensajes no guardan nada del remitente salvo el alias que el mismo
 * eligio, y vencen a los TTL_MS.
 */
import { DurableObject } from "cloudflare:workers";
import { Env } from "./util";

export const TTL_MS = 7 * 24 * 3600 * 1000;
const MAX_GUARDADOS = 200;
const HISTORIAL = 50;
export const MAX_TEXTO = 500;
export const MAX_ALIAS = 32;

export type Mensaje = {
  id: string;
  fecha: number;
  alias: string;
  texto: string;
};

export class Sala extends DurableObject<Env> {
  private sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS mensajes (
      id TEXT PRIMARY KEY, fecha INTEGER NOT NULL, alias TEXT NOT NULL, texto TEXT NOT NULL)`);
  }

  private purgar(): void {
    this.sql.exec("DELETE FROM mensajes WHERE fecha < ?", Date.now() - TTL_MS);
    this.sql.exec(
      "DELETE FROM mensajes WHERE id NOT IN (SELECT id FROM mensajes ORDER BY fecha DESC LIMIT ?)", MAX_GUARDADOS);
  }

  publicar(alias: string, texto: string): Mensaje {
    const m: Mensaje = { id: crypto.randomUUID(), fecha: Date.now(), alias, texto };
    this.sql.exec("INSERT INTO mensajes (id, fecha, alias, texto) VALUES (?, ?, ?, ?)", m.id, m.fecha, alias, texto);
    this.purgar();
    const aviso = JSON.stringify({ tipo: "mensaje", mensaje: m });
    for (const ws of this.ctx.getWebSockets()) {
      try {
        ws.send(aviso);
      } catch {
        /* conexion cerrandose */
      }
    }
    return m;
  }

  recientes(cantidad = HISTORIAL): Mensaje[] {
    this.purgar();
    return this.sql
      .exec<Mensaje>("SELECT id, fecha, alias, texto FROM mensajes ORDER BY fecha DESC LIMIT ?", cantidad)
      .toArray()
      .reverse();
  }

  async fetch(req: Request): Promise<Response> {
    if (req.headers.get("upgrade") !== "websocket") {
      return new Response("se esperaba Upgrade: websocket", { status: 426 });
    }
    const [cliente, servidor] = Object.values(new WebSocketPair());
    this.ctx.acceptWebSocket(servidor);
    servidor.send(JSON.stringify({ tipo: "historial", mensajes: this.recientes() }));
    return new Response(null, { status: 101, webSocket: cliente });
  }

  webSocketMessage(): void {
    /* Sala de solo lectura: lo que mande el navegador se ignora. */
  }

  webSocketClose(ws: WebSocket, codigo: number, motivo: string): void {
    try {
      ws.close(codigo, motivo);
    } catch {
      /* ya cerrada */
    }
  }
}

function escaparXml(texto: string): string {
  return texto.replace(/[<>&'"]/g, (c) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "'": "&apos;", '"': "&quot;" })[c]!);
}

/** Feed Atom (RFC 4287) de una sala. */
export function feedAtom(origen: string, tema: string, mensajes: Mensaje[]): string {
  const actualizado = new Date(mensajes.length ? mensajes[mensajes.length - 1].fecha : 0).toISOString();
  const entradas = [...mensajes].reverse().map((m) => {
    const autor = m.alias || "anonimo";
    const titulo = m.texto.length > 60 ? `${m.texto.slice(0, 60)}...` : m.texto;
    return `  <entry>
    <id>urn:uuid:${m.id}</id>
    <title>${escaparXml(`${autor}: ${titulo}`)}</title>
    <updated>${new Date(m.fecha).toISOString()}</updated>
    <author><name>${escaparXml(autor)}</name></author>
    <content type="text">${escaparXml(m.texto)}</content>
  </entry>`;
  });
  return `<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>FaroNet #${tema}</title>
  <id>${origen}/salas/${tema}</id>
  <updated>${actualizado}</updated>
  <link rel="self" href="${origen}/salas/${tema}/feed.xml"/>
  <link rel="alternate" href="${origen}/salas/${tema}"/>
${entradas.join("\n")}
</feed>
`;
}
