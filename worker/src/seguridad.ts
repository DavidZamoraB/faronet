/**
 * Autenticacion del gateway y limite de peticiones.
 *
 * Cada peticion del gateway lleva tres cabeceras:
 *
 *   X-Faronet-Gateway: llave publica Ed25519 del gateway (hex, 32 bytes)
 *   X-Faronet-Tiempo:  milisegundos desde 1970 (decimal)
 *   X-Faronet-Firma:   firma Ed25519 (hex, 64 bytes) de
 *
 *     "faronet-edge-v1\n" METODO "\n" RUTA "\n" TIEMPO "\n" hex(SHA-256(cuerpo))
 *
 * El Worker exige que la llave este en GATEWAYS, que el tiempo este a menos
 * de 60 s del reloj del Worker y que sea estrictamente mayor que el ultimo
 * aceptado de ese gateway (lo guarda el Durable Object Central). Asi una
 * peticion capturada no se puede repetir (replay).
 */
import { aBytes, deHex, Env, hex, sha256, verificarEd25519 } from "./util";

export const CONTEXTO = "faronet-edge-v1";
export const VENTANA_MS = 60_000;

export type Autenticacion = { ok: true; gateway: string } | { ok: false; motivo: string };

export async function autenticarGateway(req: Request, cuerpo: Uint8Array, env: Env): Promise<Autenticacion> {
  const gateway = (req.headers.get("x-faronet-gateway") ?? "").toLowerCase();
  const tiempo = req.headers.get("x-faronet-tiempo") ?? "";
  const firma = deHex(req.headers.get("x-faronet-firma") ?? "");
  const permitidos = env.GATEWAYS.split(",").map((s) => s.trim().toLowerCase()).filter(Boolean);
  if (!permitidos.includes(gateway)) return { ok: false, motivo: "gateway no autorizado" };
  if (!/^\d{1,16}$/.test(tiempo) || Math.abs(Date.now() - Number(tiempo)) > VENTANA_MS) {
    return { ok: false, motivo: "marca de tiempo fuera de la ventana" };
  }
  const llave = deHex(gateway);
  const ruta = new URL(req.url).pathname;
  const mensaje = aBytes(`${CONTEXTO}\n${req.method}\n${ruta}\n${tiempo}\n${hex(await sha256(cuerpo))}`);
  if (!llave || !firma || !(await verificarEd25519(llave, firma, mensaje))) {
    return { ok: false, motivo: "firma invalida" };
  }
  const central = env.CENTRAL.getByName("central");
  if (!(await central.marcarTiempo(gateway, Number(tiempo)))) {
    return { ok: false, motivo: "peticion repetida" };
  }
  return { ok: true, gateway };
}

/*
 * Limite de peticiones. La clave es un hash de la IP con la fecha: nunca se
 * guarda ni se registra la IP. Se usa el binding de rate limiting de
 * Cloudflare; si la cuenta no lo tiene, un contador en memoria del isolate
 * (aproximado, pero no persiste nada).
 */
const cubetas = new Map<string, { cuenta: number; desde: number }>();
const LIMITE_MEMORIA = 60;
const VENTANA_LIMITE_MS = 60_000;

export async function permitir(req: Request, env: Env, clase: string): Promise<boolean> {
  const ip = req.headers.get("cf-connecting-ip") ?? "local";
  const dia = new Date().toISOString().slice(0, 10);
  const clave = hex(await sha256(aBytes(`faronet-limite|${dia}|${clase}|${ip}`))).slice(0, 32);
  if (env.LIMITE) {
    try {
      return (await env.LIMITE.limit({ key: clave })).success;
    } catch {
      /* binding no disponible: se usa el contador en memoria */
    }
  }
  const ahora = Date.now();
  const c = cubetas.get(clave);
  if (!c || ahora - c.desde > VENTANA_LIMITE_MS) {
    if (cubetas.size > 10_000) cubetas.clear();
    cubetas.set(clave, { cuenta: 1, desde: ahora });
    return true;
  }
  c.cuenta++;
  return c.cuenta <= LIMITE_MEMORIA;
}
