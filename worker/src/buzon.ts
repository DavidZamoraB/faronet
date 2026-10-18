/**
 * Buzon muerto (dead drop): blobs cifrados de tamano fijo.
 *
 * Quien deposita y quien retira comparten un secreto. Del secreto derivan,
 * fuera del Worker, el identificador opaco del buzon y la llave con la que
 * se cifra el blob. El Worker solo ve 32 bytes aleatorios de identificador y
 * BLOB bytes cifrados: no puede leer el contenido ni saber su largo real.
 *
 * Cada blob vence a su TTL y se borra al ser leido (lectura unica). El objeto
 * es de un solo hilo, asi que leer y borrar es atomico: dos lectores nunca
 * reciben el mismo blob.
 */
import { DurableObject } from "cloudflare:workers";
import { Env } from "./util";

export const BLOB = 1024;
export const TTL_DEFECTO_S = 24 * 3600;
export const TTL_MAXIMO_S = 72 * 3600;
const MAX_BLOBS = 20_000;

export type Deposito = "ok" | "ocupado" | "lleno";

export class Buzon extends DurableObject<Env> {
  private sql: SqlStorage;

  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    this.sql = ctx.storage.sql;
    this.sql.exec(`CREATE TABLE IF NOT EXISTS blobs (
      id TEXT PRIMARY KEY, datos BLOB NOT NULL, expira INTEGER NOT NULL)`);
  }

  private purgar(): void {
    this.sql.exec("DELETE FROM blobs WHERE expira <= ?", Date.now());
  }

  async depositar(id: string, datos: Uint8Array, ttlSegundos: number): Promise<Deposito> {
    this.purgar();
    if (this.sql.exec("SELECT 1 FROM blobs WHERE id = ?", id).toArray().length) return "ocupado";
    const cantidad = this.sql.exec<{ n: number }>("SELECT COUNT(*) AS n FROM blobs").one().n;
    if (cantidad >= MAX_BLOBS) return "lleno";
    const expira = Date.now() + ttlSegundos * 1000;
    this.sql.exec("INSERT INTO blobs (id, datos, expira) VALUES (?, ?, ?)", id,
      datos.buffer.slice(datos.byteOffset, datos.byteOffset + datos.byteLength), expira);
    if ((await this.ctx.storage.getAlarm()) === null) await this.ctx.storage.setAlarm(expira);
    return "ok";
  }

  retirar(id: string): Uint8Array | null {
    this.purgar();
    const fila = this.sql.exec<{ datos: ArrayBuffer }>("SELECT datos FROM blobs WHERE id = ?", id).toArray()[0];
    if (!fila) return null;
    this.sql.exec("DELETE FROM blobs WHERE id = ?", id);
    return new Uint8Array(fila.datos);
  }

  async alarm(): Promise<void> {
    this.purgar();
    const proxima = this.sql.exec<{ e: number | null }>("SELECT MIN(expira) AS e FROM blobs").one().e;
    if (proxima !== null) await this.ctx.storage.setAlarm(proxima);
  }
}
