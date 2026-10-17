# nodo

Nodos de la red mesh FaroNet (capas 2, 3 y 7) y cliente de terminal.

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e adaptador -e nodo      # desde la raíz del repositorio
```

Queda disponible el comando `faronet` (equivalente a `python -m faronet`).

## Uso

```bash
# Nodo con identidad en un archivo, escuchando vecinos por TCP
faronet --llave ana.key --nombre ana --escuchar 0.0.0.0:9101 --vecino 192.168.1.20:9101

# Gateway con un Faro: la identidad vive en la EEPROM del Faro y el botón de pánico la borra
faronet --faro /dev/ttyUSB0 --nombre gw-norte --gateway --escuchar 0.0.0.0:9101

# Gateway conectado al Worker: publica los mensajes publicos y sube el directorio
faronet --llave gw.key --nombre gw-norte --gateway --edge https://faronet.<cuenta>.workers.dev --escuchar 0.0.0.0:9101

# Rele sin consola (servicio)
faronet --llave rele.key --escuchar 0.0.0.0:9101 --vecino 10.0.0.5:9101 --sin-consola
```

Consola: `nodos`, `rutas`, `circuitos`, `enviar <nombre|id> <texto>`,
`publicar <tema> <texto>`, `buzon`, `panico`, `salir`. Ver `faronet --help` para todos los parámetros.

Demo local con 5 reles en línea: `./demo_local.sh` (ver el comentario del script).

## Diseño

```
 aplicación   Mensaje sellado (SealedBox) de tamaño fijo, buzón con TTL     mensaje.py
 onion        circuitos de 3 a 5 saltos, una capa AEAD por salto           onion.py, cripto.py
 ruteo (L3)   celdas con DESTINO/ORIGEN de nodo, vector de distancias      ruteo.py, nodo.py
 directorio   entradas firmadas Ed25519, difundidas por inundación         directorio.py
 enlaces (L2) TCP (Ethernet/WiFi), Faro (fragmenta en tramas de 114 B)      enlaces.py
```

* **Celda** (`celda.py`): todas miden 512 bytes. Cabecera de 26 bytes con
  versión, comando, TTL, destino y origen del *tramo* (8 bytes cada uno),
  circuito y LON (largo del cuerpo significativo).
* **Circuitos negociados** (tipo Tor): el cliente crea el circuito salto por
  salto (`CREAR` al primero y `EXTENDER` dentro del circuito a los demás). El
  handshake (`cripto.py`) combina dos Diffie-Hellman X25519 y autentica al rele
  con su llave onion publicada en el directorio.
* **Capas**: XChaCha20-Poly1305 con nonce por contador. Cada salto verifica y
  quita su capa, y rellena con bytes aleatorios para que la celda siga
  midiendo 512 (`onion.py` explica la aritmética).
* **Anonimato**: el primer rele conoce al cliente pero no el destino; la salida
  conoce el destino pero no al cliente; el del medio no conoce ninguno
  (prueba `test_ningun_rele_conoce_origen_y_destino`).
* **Extremo a extremo**: el texto se sella hacia la llave onion del
  destinatario; el sobre siempre mide 391 bytes (máx. 331 bytes de texto).
* **Ruteo dinámico**: vector de distancias con horizonte dividido y
  envenenamiento en reversa, actualizaciones inmediatas y expiración. Costo
  del enlace: TCP 1, Faro 4.
* **Mensajes públicos** (`publicar`): el circuito termina en un **gateway**
  (rol en el directorio). El gateway recibe el `MensajePublico` (tamaño fijo,
  391 B) como salida del circuito y lo sube al Worker (`gateway/`), sin saber
  quién lo originó.
* **Sin registros**: nada se escribe a disco salvo la llave (si se usa
  `--llave`). No se guardan IPs de vecinos ni direcciones físicas.

## Pruebas

```bash
cd nodo && python3 -m unittest -v
```

Incluyen una red de 6 nodos en dos comunidades, una red por TCP real y una
red que cruza dos Faros simulados (`dispositivo_luz_adaptador.simulador`).

## Pendiente

* Autenticar el `HOLA` de los enlaces (hoy un vecino puede mentir sobre su
  ID; no rompe el anonimato porque el handshake autentica a cada salto, pero
  puede desviar rutas).
* Celdas de relleno (cover traffic) para dificultar el análisis de tiempos.
