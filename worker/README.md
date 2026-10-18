# worker

Capa 7 pública de FaroNet en **Cloudflare Workers** (plan gratuito): relay del
gateway, salas públicas en tiempo real, feeds Atom, buzón muerto, directorio
público y límite de peticiones.

## Rutas

| Método y ruta | Qué hace |
|---|---|
| `GET /` | Página de inicio con las salas activas |
| `GET /salas/:tema` | Sala pública en vivo (navegador, WebSocket) |
| `GET /salas/:tema/feed.xml` | Feed Atom de la sala |
| `GET /salas/:tema/mensajes` | Mensajes recientes (JSON) |
| `GET /api/salas` | Salas activas |
| `GET /api/directorio` | Réplica pública del directorio, con cada entrada cruda (base64) para verificar su firma |
| `PUT /api/buzon/:id?ttl=SEG` | Deposita un blob cifrado de 1024 bytes |
| `GET /api/buzon/:id` | Retira el blob (lectura única: se borra) |
| `POST /api/gateway/publicar` | **Firmado.** El gateway publica `{tema, texto, alias}` |
| `POST /api/gateway/directorio` | **Firmado.** El gateway sube `{entradas: [base64...]}` |

## Diseño

```
 gateway (RPi) --HTTPS firmado--> Worker --RPC--> Sala (Durable Object por tema) --WebSocket--> navegadores
                                     |-------> Central (directorio, salas, anti-replay)
 cualquiera  ----PUT/GET blob----->  |-------> Buzon (blobs con TTL)
```

* **Autenticación del gateway** (`src/seguridad.ts`): firma Ed25519 de
  `"faronet-edge-v1\n" METODO "\n" RUTA "\n" TIEMPO_MS "\n" hex(SHA-256(cuerpo))`.
  La llave tiene que estar en `GATEWAYS`; el tiempo, a menos de 60 s del reloj
  del Worker y **estrictamente mayor** que el último aceptado de ese gateway
  (guardado en el Durable Object `Central`). Una petición capturada no se puede
  repetir ni alterar.
* **Salas** (`src/sala.ts`): un Durable Object SQLite por tema, con la API de
  hibernación de WebSockets. De solo lectura desde clearnet. Guardan como
  máximo 200 mensajes y 7 días.
* **Buzón muerto** (`src/buzon.ts`): el identificador y la llave se derivan de
  un secreto compartido **fuera** del Worker (`gateway/faronet_gateway/edge.py`),
  así que el Worker solo ve 32 bytes opacos y 1024 bytes cifrados. TTL de
  1 min a 72 h (24 h por defecto) y lectura única atómica.
* **Directorio** (`src/central.ts`): el Worker verifica la firma Ed25519 de cada
  entrada antes de publicarla y publica los bytes originales, para que cualquiera
  la vuelva a verificar.
* **Límite de peticiones**: 60 por minuto por cliente, con el binding de rate
  limiting de Cloudflare (o un contador en memoria si la cuenta no lo tiene).
  La clave es `SHA-256(fecha | clase | IP)`: la IP no se guarda.
* **Política de no registro**: el código no persiste ni escribe en logs
  `CF-Connecting-IP`, `User-Agent` ni otras cabeceras del visitante, y
  `observability` está desactivado en `wrangler.toml`. Las páginas llevan una
  CSP estricta con nonce.

### Qué sigue viendo Cloudflare (para el modelo de amenazas)

Aunque el código no lo guarde, Cloudflare como proveedor termina TLS y ve la IP
de cada visitante y del gateway, el momento y el tamaño de cada petición, las
rutas (incluido el identificador del buzón) y el contenido de las salas
públicas, que de por sí es público. Puede tener sus propios registros de red
fuera del control del Worker. Nunca ve el texto del buzón muerto ni quién
originó un mensaje dentro de FaroNet: solo ve al gateway.

## Desarrollo local (sin cuenta)

```bash
cd worker
npm install
npx wrangler dev --var GATEWAYS:<llave_publica_hex>
```

Pruebas de integración (levantan `wrangler dev` solas):

```bash
pip install -e adaptador -e nodo -e gateway     # desde la raíz, en el venv
cd gateway && python -m unittest -v
```

## Despliegue

```bash
cd worker
npx wrangler login                 # una vez, abre el navegador
# poner en wrangler.toml -> GATEWAYS la llave del gateway:
faronet-edge llave --llave ~/llaves/gateway.key
npx wrangler deploy
```

No hay secretos en el repositorio: `GATEWAYS` son llaves **públicas**.
