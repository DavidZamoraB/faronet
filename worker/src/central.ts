/**
 * Durable Object unico ("central"): replica publica del directorio de nodos,
 * lista de salas y ultimo tiempo aceptado de cada gateway (anti-replay).
 *
 * Formato de una entrada del directorio (igual que nodo/faronet/directorio.py):
 *
 *   VER(1) ID(8) LLAVE_FIRMA(32) LLAVE_ONION(32) ROLES(1) PUBLICADA(4) EXPIRA(4)
 *   LON_NOMBRE(1) NOMBRE(LON) FIRMA(64)
 *
 * La FIRMA (Ed25519, de LLAVE_FIRMA) cubre todos los bytes anteriores. El
 * Worker la verifica antes de aceptar la entrada y publica la entrada cruda,
 * para que cualquiera pueda volver a verificarla.
 */
import { DurableObject } from "cloudflare:workers";
import { b64, Env, hex, verificarEd25519 } from "./util";

const FIJO = 83;
const FIRMA = 64;
const MAX_VIGENCIA_S = 3600;
const TOLERANCIA_S = 300;
const INACTIVIDAD_TEMA_MS = 30 * 24 * 3600 * 1000;

export interface EntradaPublica {
  id: string;
  nombre: string;
  roles: string[];
  llave_firma: string;
  llave_onion: string;
  publicada: number;
  expira: number;
  entrada: string; // bytes originales en base64, verificables
}

interface EntradaLeida {
  id: string;
  nombre: string;
  roles: number;
  publicada: number;
  expira: number;
}

async function leerEntrada(datos: Uint8Array): Promise<EntradaLeida | null> {
  if (datos.length < FIJO + FIRMA || datos[0] !== 1) return null;
  const v = new DataView(datos.buffer, datos.byteOffset, datos.byteLength);
  const lon = datos[82];
  const fin = FIJO + lon;
  if (lon > 32 || datos.length !== fin + FIRMA) return null;
  const llave = datos.slice(9, 41);
  const publicada = v.getUint32(74);
  const expira = v.getUint32(78);
  const ahora = Date.now() / 1000;
  if (expira <= ahora || publicada > ahora + TOLERANCIA_S || expira - publicada > MAX_VIGENCIA_S) return null;
  if (!(await verificarEd25519(llave, datos.slice(fin), datos.slice(0, fin)))) return null;
  let nombre: string;
  try {
    nombre = new TextDecoder("utf-8", { fatal: true, ignoreBOM: false }).decode(datos.slice(FIJO, fin));
  } catch {
    return null;
  }
  return { id: hex(datos.slice(1, 9)), nombre, roles: datos[73], publicada, expira };
}

export class Central extends DurableObject<Env> {
  private sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`
      CREATE TABLE IF NOT EXISTS gateways (id TEXT PRIMARY KEY, ultimo INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS directorio (
        id TEXT PRIMARY KEY, entrada BLOB NOT NULL, publicada INTEGER NOT NULL, expira INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS temas (tema TEXT PRIMARY KEY, ultimo INTEGER NOT NULL);
    `);
  }

  /** true si `tiempo` es mayor que el ultimo aceptado de ese gateway. */
  marcarTiempo(gateway: string, tiempo: number): boolean {
    const fila = this.sql.exec<{ ultimo: number }>("SELECT ultimo FROM gateways WHERE id = ?", gateway).toArray()[0];
    if (fila && tiempo <= fila.ultimo) return false;
    this.sql.exec(
      "INSERT INTO gateways (id, ultimo) VALUES (?, ?) ON CONFLICT(id) DO UPDATE SET ultimo = excluded.ultimo",
      gateway, tiempo,
    );
    return true;
  }

  async guardarEntradas(entradas: Uint8Array[]): Promise<{ aceptadas: number; rechazadas: number }> {
    let aceptadas = 0;
    for (const datos of entradas) {
      const e = await leerEntrada(datos);
      if (!e) continue;
      const actual = this.sql
        .exec<{ publicada: number }>("SELECT publicada FROM directorio WHERE id = ?", e.id).toArray()[0];
      if (actual && actual.publicada >= e.publicada) continue;
      this.sql.exec(
        "INSERT OR REPLACE INTO directorio (id, entrada, publicada, expira) VALUES (?, ?, ?, ?)",
        e.id, datos.buffer.slice(datos.byteOffset, datos.byteOffset + datos.byteLength), e.publicada, e.expira,
      );
      aceptadas++;
    }
    return { aceptadas, rechazadas: entradas.length - aceptadas };
  }

  async directorio(): Promise<EntradaPublica[]> {
    this.sql.exec("DELETE FROM directorio WHERE expira <= ?", Math.floor(Date.now() / 1000));
    const filas = this.sql.exec<{ entrada: ArrayBuffer }>("SELECT entrada FROM directorio ORDER BY id").toArray();
    const salida: EntradaPublica[] = [];
    for (const { entrada } of filas) {
      const datos = new Uint8Array(entrada);
      const e = await leerEntrada(datos);
      if (!e) continue;
      salida.push({
        id: e.id,
        nombre: e.nombre,
        roles: [e.roles & 1 ? "rele" : "", e.roles & 2 ? "gateway" : ""].filter(Boolean),
        llave_firma: hex(datos.slice(9, 41)),
        llave_onion: hex(datos.slice(41, 73)),
        publicada: e.publicada,
        expira: e.expira,
        entrada: b64(datos),
      });
    }
    return salida;
  }

  tocarTema(tema: string): void {
    this.sql.exec(
      "INSERT INTO temas (tema, ultimo) VALUES (?, ?) ON CONFLICT(tema) DO UPDATE SET ultimo = excluded.ultimo",
      tema, Date.now(),
    );
  }

  temas(): { tema: string; ultimo: number }[] {
    this.sql.exec("DELETE FROM temas WHERE ultimo < ?", Date.now() - INACTIVIDAD_TEMA_MS);
    return this.sql.exec<{ tema: string; ultimo: number }>(
      "SELECT tema, ultimo FROM temas ORDER BY ultimo DESC LIMIT 100").toArray();
  }
}
