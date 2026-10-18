/** Utilidades compartidas: codificaciones, WebCrypto y respuestas HTTP. */

export interface Env {
  CENTRAL: DurableObjectNamespace<import("./central").Central>;
  SALAS: DurableObjectNamespace<import("./sala").Sala>;
  BUZON: DurableObjectNamespace<import("./buzon").Buzon>;
  LIMITE?: RateLimit;
  GATEWAYS: string;
}

const enc = new TextEncoder();

export function aBytes(texto: string): Uint8Array {
  return enc.encode(texto);
}

export function hex(datos: ArrayBuffer | Uint8Array): string {
  return [...new Uint8Array(datos)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function deHex(texto: string): Uint8Array | null {
  if (!/^(?:[0-9a-fA-F]{2})*$/.test(texto)) return null;
  const salida = new Uint8Array(texto.length / 2);
  for (let i = 0; i < salida.length; i++) salida[i] = parseInt(texto.slice(2 * i, 2 * i + 2), 16);
  return salida;
}

export function b64(datos: Uint8Array): string {
  let s = "";
  for (const b of datos) s += String.fromCharCode(b);
  return btoa(s);
}

export function deB64(texto: string): Uint8Array | null {
  try {
    return Uint8Array.from(atob(texto), (c) => c.charCodeAt(0));
  } catch {
    return null;
  }
}

export async function sha256(datos: Uint8Array): Promise<Uint8Array> {
  return new Uint8Array(await crypto.subtle.digest("SHA-256", datos));
}

export async function verificarEd25519(llave: Uint8Array, firma: Uint8Array, datos: Uint8Array): Promise<boolean> {
  if (llave.length !== 32 || firma.length !== 64) return false;
  try {
    const k = await crypto.subtle.importKey("raw", llave, { name: "Ed25519" }, false, ["verify"]);
    return await crypto.subtle.verify("Ed25519", k, firma, datos);
  } catch {
    return false;
  }
}

/** Nombres de sala: minusculas, numeros y guiones; maximo 32. */
export const TEMA = /^[a-z0-9][a-z0-9-]{0,31}$/;

const SEGURIDAD: Record<string, string> = {
  "x-content-type-options": "nosniff",
  "referrer-policy": "no-referrer",
  "cache-control": "no-store",
};

export function json(datos: unknown, estado = 200): Response {
  return new Response(JSON.stringify(datos), {
    status: estado,
    headers: { "content-type": "application/json; charset=utf-8", ...SEGURIDAD },
  });
}

export function error(estado: number, mensaje: string): Response {
  return json({ error: mensaje }, estado);
}

export function respuesta(cuerpo: BodyInit | null, tipo: string, extra: Record<string, string> = {}): Response {
  return new Response(cuerpo, { headers: { "content-type": tipo, ...SEGURIDAD, ...extra } });
}

/** Lee el cuerpo completo, con un limite de tamano. null si se pasa. */
export async function leerCuerpo(req: Request, maximo: number): Promise<Uint8Array | null> {
  const declarado = Number(req.headers.get("content-length") ?? "0");
  if (declarado > maximo) return null;
  const datos = new Uint8Array(await req.arrayBuffer());
  return datos.length > maximo ? null : datos;
}
