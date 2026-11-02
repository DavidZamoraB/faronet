---
title: "Proyecto 1: FaroNet"
subtitle: "Documentación del proyecto"
author:
  - David Zamora
  - Diego Zamora
institute: "Instituto Tecnológico de Costa Rica · Escuela de Computación · Redes de Computadoras · Prof. Kevin Moraga"
date: "Noviembre, 2026"
lang: es
---

> **Estado de este documento.** Versión del 2 de noviembre de 2026, escrita a
> partir de `main` (commit `b1d3ada`). Los puntos marcados como
> **[PENDIENTE]** son trabajo que todavía no está hecho o datos que solo el
> equipo puede llenar (horas, autoevaluación, mediciones). No se reportan
> resultados que no se hayan medido.

# 1. Introducción

Hoy cifrar el contenido de un mensaje no basta para proteger a quien lo
envía. Los **metadatos** (quién habla con quién, cuándo, desde dónde y con
qué frecuencia) bastan para vigilar a una persona aunque nunca se lea una
sola palabra de lo que escribe. FaroNet es una red de mensajería construida
desde el cobre hacia arriba cuyo objetivo es proteger también esos
metadatos.

El proyecto se apoya en cuatro piezas, cada una sobre la anterior:

1. **El Faro**: un dispositivo soldado que transmite y recibe datos con luz
   infrarroja, conectado por USB a la computadora de un nodo.
2. **Un protocolo de enlace propio (Capa 1)**: tramas de hasta 128 bytes con
   CRC, acceso al medio, versión y una dirección física rotable.
3. **Una mesh anónima (Capas 2 y 3)**: enruta celdas de tamaño fijo por
   Ethernet, WiFi o el Faro, con circuitos onion de 3 a 5 saltos, de modo
   que ningún nodo intermedio conoce a la vez el origen y el destino.
4. **Una salida a Internet en el edge (Capa 7)**: un gateway que publica solo
   los mensajes marcados como públicos en Cloudflare Workers (salas en
   tiempo real, feeds Atom, buzón muerto y directorio público), sin guardar
   datos que identifiquen a los usuarios.

Las comunidades de FaroNet están separadas y solo se unen por un par de
Faros:

```
     Comunidad A                                   Comunidad B
 +---------+  TCP  +---------+  USB  +------+         +------+  USB  +-------------+
 | Nodo PC |-------|  Nodo   |-------|Faro A|~~ luz ~~|Faro B|-------| Gateway RPi |
 +---------+       +---------+       +------+         +------+       +-------------+
      |                                                                     |
      +------------- mesh anónima (Ethernet / WiFi / Faro) -----------------+
                                                                            | HTTPS firmado
                                                                            v
                                                              +---------------------------+
                                                              | Edge: Cloudflare Workers  |
                                                              +---------------------------+
                                                                            |
                                                          clearnet (navegador, feeds)
```

## Estrategia de solución

Ninguno de los dos integrantes tenía experiencia previa en electrónica,
protocolos de enlace, mesh, criptografía aplicada ni serverless (ver el
diagnóstico del kick-off, `docs/kickoff/Kickoff_FaroNet.docx`). Por eso se
construyó **de abajo hacia arriba**, validando cada capa antes de pasar a la
siguiente:

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Aprendizaje base (electrónica, Arduino, sockets, criptografía) | Hecho |
| 1 | Prototipo del Faro en protoboard, luz entre dos Faros | Hecho (cada Faro por separado) |
| 2 | Capa 1: trama, CRC, acceso al medio, medición de tasa y BER | Protocolo hecho; medición **[PENDIENTE]** |
| 3 | Faro soldado en placa perforada, pruebas de multímetro | En curso |
| 4 | Mesh FaroNet: directorio, ruteo, onion routing | Hecho |
| 5 | Gateway (Raspberry Pi) y Cloudflare Workers | Hecho y desplegado |
| 6 | RFC, documentación y ensayo de la defensa | RFC hecho; este documento |

Para no frenar el software mientras se armaba el hardware, la biblioteca
incluye un **simulador del Faro** (`adaptador/dispositivo_luz_adaptador/simulador.py`)
que imita el firmware y un medio con BER configurable. Así la mesh se
programó y probó sin tener los Faros soldados.

# 2. Ambiente de desarrollo

## Software

| Uso | Herramienta |
|---|---|
| Sistemas operativos | GNU/Linux (Ubuntu) en las PC; Raspberry Pi OS en los nodos Raspberry Pi |
| Editor | Visual Studio Code |
| Firmware del Faro | Arduino (C/C++), Arduino IDE y `arduino-cli` con el core `arduino:avr` |
| Pruebas del núcleo del firmware | `g++ -std=c++11` en la PC (`firmware/faro/test/test_core.cpp`) |
| Biblioteca, nodos y gateway | Python 3.12, `pyserial`, PyNaCl (libsodium), Scapy (opcional) |
| Aplicación en el edge | TypeScript sobre Cloudflare Workers (plan gratuito), Durable Objects con SQLite, `wrangler`, Node.js 22 |
| Integración continua | GitHub Actions (`.github/workflows/ci.yml`) |
| Control de versiones | Git y GitHub, una rama por funcionalidad y pull requests |
| Documentación | Markdown → PDF con Pandoc; RFC en texto ASCII paginado con `paginar.py` |
| Asistencia | Claude (Anthropic) como asistente de programación, revisión y redacción |

## Hardware y herramientas físicas

* Arduino Uno R3 (clon, ATmega328P DIP) y Arduino Nano; el firmware compila
  para ambos.
* Raspberry Pi 2 y Raspberry Pi 3/4 como nodos (`faronet-sur` de David y
  `faronet-gw` de Diego).
* Cautín, estaño con resina, malla desoldante, pinzas y soporte.
* Multímetro digital: continuidad, resistencia, ausencia de corto entre +5 V
  y GND antes de energizar y voltajes en puntos clave.
* Protoboard para el prototipo y placa perforada (HS-03) para la versión
  final.

## Depuración

* **Faro**: LEDs TX/RX/estado, los comandos `faro sondear --continuo` (lee A0
  y la salida del comparador) y `faro emisor encender|apagar` (LED IR fijo
  para medir con el multímetro), y `hardware/calibrar_receptor.py`.
* **Protocolo**: pruebas unitarias contra Faros simulados y contra el núcleo
  C++ del firmware; Scapy (`scapy_faro.FaroTrama`) para armar tramas a mano.
* **Mesh**: consola del nodo (`nodos`, `rutas`, `circuitos`) y
  `nodo/demo_local.sh` (5 relés locales). Nada se escribe a disco, por la
  política de no registro.
* **Edge**: `wrangler dev` local y pruebas de integración en `gateway/tests`.

## Flujo de trabajo con Git

* `main` siempre estable y compilable.
* Una rama por funcionalidad (`feature/faro-capa1`, `feature/mesh-onion`,
  `feature/puente-edge`, `feature/despliegue-worker`, `feature/rfc`,
  `feature/temas-privados`, ...), integrada por pull request que revisa y
  fusiona el otro integrante.
* Cada pull request corre la CI: pruebas de `adaptador/` (incluidas las del
  núcleo C++), pruebas de `nodo/`, verificación de tipos del Worker con
  pruebas de integración contra `wrangler dev`, y compilación del firmware
  para Nano y Uno.
* No se suben secretos: el Worker solo tiene llaves **públicas** de gateways
  en `wrangler.toml`.

Repositorio: <https://github.com/DavidZamoraB/faronet>

# 3. Diseño

Esta sección explica las decisiones. La especificación completa está en el
RFC (`docs/rfc-faronet.txt`, anexo al final de este PDF).

## 3.1 Hardware: el Faro

El Faro es un Arduino (Uno o Nano) con cinco bloques:

```
                +----------------------------------------------+
   USB (nodo) ==|  Arduino Uno / Nano                          |
                |  D4 ----> [ Emisor: 2N2222A + LED IR ]  ~~~> luz
   luz ~~~>  [ Receptor: fototransistor -> LM393 ] ----> D2    |
                |              \--------------------> A0      |
                |  D5 -> LED TX    D6 -> LED RX    D7 -> LED   |
                |  D3 <- botón de pánico                       |
                +----------------------------------------------+
```

| Pin | Función |
|---|---|
| D2 | Salida del comparador (interrupción INT0) |
| D3 | Botón de pánico a GND (pull-up interno) |
| D4 | Base del 2N2222A que maneja el LED IR (vía R2 = 1 kΩ) |
| D5 / D6 / D7 | LED TX (verde) / LED RX (amarillo) / LED estado-pánico (rojo) |
| A0 | Voltaje del fototransistor (solo calibración) |

**Emisor.** LED IR de 940 nm con R1 = 82 Ω y un 2N2222A como interruptor.
Corriente del LED ≈ (5 − 1,2 − 0,2) V / 82 Ω ≈ 44 mA; corriente de base
≈ 4,3 mA, β forzado ≈ 10, así que el transistor satura. Se usa transistor
porque un pin del ATmega328P no debe dar 44 mA.

**Receptor.** Fototransistor IR (con R3 a GND) cuyo voltaje entra a un
comparador LM393. El umbral es un **divisor fijo** R9 = 10 kΩ / R10 = 1 kΩ
(≈ 0,45 V). R4 = 1,5 MΩ da histéresis y R5 = 10 kΩ es el pull-up de la salida
de colector abierto. Se usa comparador y no solo la entrada analógica porque
`analogRead` tarda ≈ 100 µs, demasiado para Manchester a varios kbit/s; el
comparador entrega flancos limpios a la interrupción de D2.

**Cambios que dejó la práctica** (detalle en `hardware/bom.md`):

| Pieza | Diseño original | Final | Razón |
|---|---|---|---|
| Umbral | Trimpot RV1 10 kΩ | Divisor fijo R9/R10 | El trimpot del kit no variaba el voltaje |
| R4 | 1 MΩ | 1,5 MΩ | Disponibilidad; funciona igual |
| R5 | 4,7 kΩ | 10 kΩ | Disponibilidad; sirve como pull-up |

El Faro de Diego funcionó en protoboard el 20-10-2026 (A0 ≈ 55 con el LED
apagado y ≈ 272 encendido). El de David pasó la prueba de recepción el
31-10-2026 (A0 de 2 a 162, frente a frente a 1 cm), pero su sensor resultó
débil y el margen es justo para 1–2 m; la mejora propuesta es un
fototransistor de 940 nm (PT333-3C) o R3 = 100 kΩ.

**Esquemático.** El esquemático por bloques, los cálculos y la netlist para
KiCad están en `hardware/esquematico.md`. **[PENDIENTE]** el proyecto KiCad en
`hardware/kicad/` y su exportación en PDF.

**Placa perforada.** El circuito se suelda en placa perforada con zócalo
DIP-8 para el LM393 y headers hembra para retirar el Arduino sin desoldar
(`hardware/placa_perforada.md`). Al 2 de noviembre el Faro de David
(placa HS-03) tiene terminadas y probadas con multímetro las etapas de
alimentación (3A: rieles de 5 V y tierra, sin corto), divisor de umbral (3B)
y se está soldando el receptor (3C); falta el emisor (etapa 4).
**[PENDIENTE]** fotos de ambas caras (`hardware/fotos/`) y la bitácora de
multímetro llena para cada Faro (`hardware/bitacora_pruebas.md`).

**BOM.** `hardware/bom.md`: ≈ ₡10 675 por Faro y ≈ ₡26 910 para los dos Faros
más materiales compartidos (precios aproximados de octubre de 2026; se deben
reemplazar por los de la factura).

## 3.2 Capa 1: protocolo del Faro

| Decisión | Elección | Por qué |
|---|---|---|
| Codificación de línea | OOK con **Manchester** (IEEE 802.3) | Auto-sincronizante (corrige el desfase de reloj entre Arduinos en cada bit), nivel promedio constante (umbral estable) y detecta errores de línea antes del CRC. Cuesta el doble de ancho de banda. |
| Velocidad | 500–20 000 bit/s, 2 000 por defecto | Ajustable para buscar el máximo a cada distancia |
| Sincronización | Preámbulo 4 × `0x55` + SFD `0xD5` | Si llega el patrón negado, el receptor invierte los bits: la polaridad del hardware no importa |
| Trama | 12 B de cabecera + 0–114 B de carga + CRC-16 = máx. 128 B | Cumple el límite del enunciado |
| Integridad | CRC-16/CCITT-FALSE | Detecta todos los errores de 1 y 2 bits y ráfagas de hasta 16 |
| Dirección física | 4 bytes en EEPROM, rotable | 2³² direcciones bastan para decenas de Faros y ahorran 4 B por trama frente a 6 |
| Acceso al medio | CSMA/CA con espera aleatoria exponencial (8→64 ranuras), DIFS 32 bits, SIFS 12 bits, ACK y hasta 3 reintentos | Semidúplex sin detección de colisiones; el ACK tiene prioridad (SIFS < DIFS) y se descartan duplicados |
| Versionado | VERSION y LON siempre en los bytes 0 y 1; la trama mide siempre 12 + LON + 2 | Un receptor sabe dónde termina una trama aunque no entienda su versión |
| Interfaz nodo ↔ Faro | USB-serial 115 200 8N1, paquetes `COBS(tipo|datos|CRC-16)` terminados en `0x00` | Se resincroniza tras cualquier basura en la línea |

```
  0                   1                   2                   3
  0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |    VERSION    |      LON      |BANDER.| TIPO  |      SEQ      |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                     DIRECCION DESTINO (4)                     |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                     DIRECCION ORIGEN (4)                      |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |                 CARGA (LON bytes, 0 a 114) ...                |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
 |             CRC-16            |
 +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

El nodo puede entregar una **trama armada fuera del Faro** (por ejemplo con
Scapy) con el comando `ENVIAR_CRUDA`: el Faro solo verifica que su longitud sea
coherente con LON y la transmite tal cual.

## 3.3 Capas 2 y 3: la mesh FaroNet

* **Identidad**: cada nodo tiene una semilla de 32 bytes de la que salen una
  llave Ed25519 (firma) y una X25519 (onion). El ID de nodo son 8 bytes de
  BLAKE2b de la llave de firma.
* **Celdas de 512 bytes** siempre, con cabecera de 26 bytes (versión,
  comando, TTL, destino y origen *del tramo*, circuito y LON). El tamaño fijo
  impide que la longitud filtre información.
* **Enlaces**: TCP (Ethernet o WiFi, costo 1) y Faro (costo 4). En el Faro
  una celda se fragmenta en 5 tramas (4 de 112 B de datos y 1 de 64), así
  que el largo de las tramas tampoco revela el largo del mensaje.
* **Ruteo dinámico**: vector de distancias al estilo RIP, con horizonte
  dividido, envenenamiento en reversa, métrica infinita 16 y expiración a los
  3 intervalos. Cada celda se reenvía al vecino más cercano al destino.
* **Directorio de nodos**: cada nodo publica una entrada firmada con Ed25519
  (ID, llaves, roles, seudónimo, vigencia de 10 min) que se difunde por
  inundación. No hay servidor central: una entrada alterada no verifica. Las
  entradas no contienen IP ni direcciones físicas.
* **Circuitos virtuales negociados**, al estilo Tor: el cliente elige 3 a 5
  relés al azar y extiende el circuito salto por salto. El handshake (tipo
  ntor) combina dos X25519 (efímera-efímera para secreto hacia adelante y
  efímera-estática para autenticar al relé).
* **Capas de la cebolla**: XChaCha20-Poly1305 con nonce por contador, una
  capa por salto. Cada salto quita su capa y rellena con bytes aleatorios
  nuevos, así la celda sigue midiendo 512 y no se puede seguir comparando
  bytes.

El resultado es que el primer relé conoce al cliente pero no el destino, la
salida conoce el destino pero no al cliente y el relé del medio no conoce a
ninguno (lo comprueba la prueba `test_ningun_rele_conoce_origen_y_destino`).

## 3.4 Capa 7 dentro de FaroNet

* **Mensajes privados**: el texto se sella (SealedBox) hacia la llave onion
  del destinatario. El sobre mide siempre 391 bytes (hasta 331 de texto) y
  tiene TTL (24 h por defecto); los mensajes recibidos viven solo en memoria.
* **Temas privados**: un tema marcado como privado se envía a cada miembro
  como mensaje privado; el nombre del tema va dentro del sobre y estos
  mensajes nunca salen a clearnet (`publicar` sobre un tema privado da error).
* **Mensajes públicos**: el circuito termina en un nodo con rol gateway, que
  recibe un `MensajePublico` de tamaño fijo y lo sube al edge sin saber quién
  lo originó.

## 3.5 Capa 7 en el edge (Cloudflare Workers)

* **Relay del gateway**: el gateway firma cada petición con Ed25519 sobre
  `"faronet-edge-v1" | método | ruta | tiempo_ms | SHA-256(cuerpo)`. El Worker
  exige que la llave esté en `GATEWAYS`, que el tiempo esté a menos de 60 s y
  que sea estrictamente mayor que el último aceptado (anti-replay).
* **Salas públicas**: un Durable Object (SQLite) por tema con WebSockets
  hibernables; máximo 200 mensajes y 7 días.
* **Feed Atom** por tema en `/salas/:tema/feed.xml`.
* **Buzón muerto**: blobs de 1024 bytes cifrados con una llave derivada de un
  secreto compartido fuera del Worker, identificador opaco, TTL de 1 min a
  72 h y lectura única atómica.
* **Directorio público**: el Worker verifica la firma de cada entrada y
  publica los bytes originales para que cualquiera la vuelva a verificar.
* **Rate limiting**: 60 peticiones por minuto con la clave
  `SHA-256(fecha | clase | IP)`; la IP no se guarda.
* **No registro**: el código no persiste `CF-Connecting-IP` ni `User-Agent`,
  `observability` está desactivado y las páginas usan CSP con nonce.

Despliegue: <https://faronet.faronet-worker.workers.dev> (PR #6). Según el
README del Worker se probó de punta a punta: cliente → circuito onion de 3
saltos en la Raspberry Pi → gateway → Worker → sala `#general`.

## 3.6 Modelo de amenazas

Objetivo: ningún adversario individual debe poder saber a la vez quién envía
un mensaje y a quién (o que el remitente es el autor de un mensaje público).

| Adversario | Qué ve | Qué no debe ver | Mitigación |
|---|---|---|---|
| Nodo malicioso de la mesh | Su vecino anterior y siguiente, hora y cantidad de celdas | Origen y destino a la vez; el contenido | Circuitos de 3–5 saltos, celdas de 512 B, relleno nuevo por salto, cifrado extremo a extremo |
| Observador del medio físico (luz) | Que hay transmisión, cuándo, tamaño de trama, direcciones físicas actuales | El contenido; seguir a un Faro en el tiempo | Cifrado por capas y extremo a extremo; rotación de la dirección física con intervalo aleatorio |
| Operador del gateway | Mensajes públicos que salen, hora, tema y alias | El autor de los públicos; los privados | Los privados no salen de FaroNet; el gateway es la salida de un circuito y no conoce al cliente |
| Proveedor del edge (Cloudflare) | IP del gateway y de los navegadores, horas, tamaños y rutas (incluido el ID del buzón) | El contenido del buzón; quién originó un mensaje | Blobs cifrados de tamaño fijo con TTL; el Worker no guarda IP ni User-Agent; la clave del rate limit es un hash |
| Ladrón del Faro | EEPROM y memoria del Faro | Llaves e identidad, si se presionó el pánico | Botón de pánico: borra el secreto y cambia la dirección |

**Fuera de alcance**: un adversario global que vea entrada y salida de un
circuito (correlación por tiempo), varios relés que colaboren siendo primero
y último salto, ataques Sybil al directorio y un adversario con acceso al USB
del Faro antes del pánico.

**Limitaciones conocidas** (también en el RFC):

* Los enlaces TCP y Faro no van cifrados entre vecinos, así que los IDs de
  nodo de cada tramo viajan en claro dentro de las celdas. Por eso rotar la
  dirección física dificulta, pero no impide del todo, seguir a un nodo.
* El `HOLA` de los enlaces no está autenticado: un vecino puede mentir sobre
  su ID y desviar rutas (no rompe el anonimato porque el handshake autentica
  a cada salto). **[PENDIENTE]**
* No hay tráfico de cobertura: el comando `RELLENO` está reservado pero no
  implementado. **[PENDIENTE]**

## 3.7 Privacidad: requisitos del enunciado

| Requisito | Cómo se cumple |
|---|---|
| Anonimato del origen | Circuitos onion de 3 a 5 saltos |
| Cifrado extremo a extremo | SealedBox de libsodium (PyNaCl); WebCrypto en el Worker. No hay primitivas propias |
| Padding a tamaño fijo | Celdas de 512 B, sobres de 391 B, blobs de 1024 B, 5 tramas por celda en el Faro |
| Direcciones físicas rotables | `faro direccion --rotar` y rotación automática cada 600 s ± 20 % con `os.urandom` |
| Botón de pánico | Sobrescribe el secreto de la EEPROM (`0xFF` y luego `0x00`), cambia la dirección, borra buffers y estadísticas, avisa al nodo (que borra llaves, circuitos, rutas, directorio y buzón) y parpadea; el LED rojo queda encendido |
| Sin registros | Nodos solo escriben la semilla (si se usa `--llave`); el Faro solo tiene contadores en RAM; el Worker no guarda IP ni User-Agent; todo mensaje almacenado tiene TTL |

# 4. Estructuras de datos y funciones principales

## 4.1 Firmware (`firmware/faro/`)

| Elemento | Descripción |
|---|---|
| `DecodificadorManchester` (`faro_core.h`) | Máquina de estados que corre dentro de la interrupción de D2: recibe el tiempo entre flancos y el nivel. Estados `RX_CAZANDO` → `RX_SINCRONIZADO` → `RX_RECIBIENDO` → `RX_LISTA`; detecta la polaridad con el SFD |
| `crc16`, `trama_armar`, `trama_longitud_valida`, `trama_crc_valido`, `cobs_codificar/decodificar` (`faro_core.cpp`) | Lógica sin hardware, compartida con las pruebas en la PC |
| `struct Estadisticas` (`faro.ino`) | Contadores: tramas TX/RX, CRC malos, sin ACK, retransmisiones, truncadas |
| `Visto vistos[8]` | Tabla circular (origen, SEQ) para no entregar duplicados |
| `emitir_trama`, `emitir_byte` | Emisión Manchester con temporización por `micros()` |
| `canal_ocupado` | Escucha de portadora: intervalos Manchester válidos o trama en curso |
| `procesar_recepcion`, `enviar_ack`, `es_duplicado` | Recepción, ACK tras SIFS y supresión de duplicados |
| `ejecutar_panico`, `revisar_boton_panico` | Zeroize del secreto, nueva dirección, limpieza y aviso al nodo |
| `cargar_eeprom`, `guardar_direccion`, `generar_direccion` | Dirección física y configuración en EEPROM |

## 4.2 Biblioteca DispositivoLuzAdaptador (`adaptador/`)

| Elemento | Descripción |
|---|---|
| `DispositivoLuzAdaptador` | Clase principal: `abrir/cerrar`, `info`, `enviar(destino, datos)` (unicast con ACK o difusión), `enviar_trama` (trama cruda), `recibir`/`al_recibir`, `al_panico`, `rotar_direccion`, `rotacion_automatica`, `guardar_secreto`/`leer_secreto`, `configurar`, `sondear`, `emisor_fijo` |
| `Trama` (`trama.py`) | `a_bytes()` / `desde_bytes()` con verificación de CRC; constantes `MAX_TRAMA = 128`, `MAX_CARGA = 114`, `DIFUSION` |
| `crc16`, `cobs.codificar/decodificar` | Iguales a las del firmware (una prueba verifica que las constantes coincidan) |
| `enlace.py` | Códigos de comandos, respuestas, eventos y estados del protocolo serial |
| `ResultadoTx`, `TramaRecibida`, `InfoFaro`, `Estadisticas` | Resultados tipados de cada comando |
| `medicion.py` | `emisor()` y `receptor()` para medir tasa efectiva y BER; `guardar_csv()` |
| `simulador.py` | `MedioSimulado(ber)` y `FaroSimulado`: imitan el firmware para probar sin hardware |
| `scapy_faro.FaroTrama` | Capa Scapy de la trama, con CRC calculado en `post_build` |

## 4.3 Nodo de la mesh (`nodo/faronet/`)

| Módulo | Estructuras y funciones |
|---|---|
| `celda.py` | `Celda` (512 B; `a_bytes`, `desde_bytes`), comandos `HOLA`, `RUTAS`, `DIRECTORIO`, `CREAR`, `CREADA`, `RELE_IDA`, `RELE_VUELTA`, `DESTRUIR`, `ENTREGA` |
| `cripto.py` | `Identidad` (semilla, firma, abrir sobre, `borrar`), `cerrar_sobre`, `HandshakeCliente` y `handshake_rele` (ntor), `CapaOnion` (`cifrar`/`descifrar` por sentido) |
| `onion.py` | `envolver`, `desenvolver`, `quitar_capa`, `agregar_capa`, `originar`; constantes `SOBRE = 391`, `MIN_SALTOS = 3`, `MAX_SALTOS = 5` |
| `ruteo.py` | `TablaRutas` (`procesar_anuncio`, `siguiente`, `anuncio_para` con horizonte dividido, `enlace_caido`, `purgar`) |
| `directorio.py` | `Entrada` firmada (`publicar`, `desde_bytes` con verificación) y `Directorio` (`agregar`, `buscar`, `purgar`, `borrar`) |
| `enlaces.py` | `Enlace` abstracto; `EnlaceTCP`, `ServidorTCP`, `EnlaceFaro` (fragmentación en 5 tramas y reensamblado) y `EnlaceMemoria` para pruebas |
| `mensaje.py` | `Mensaje` privado (`sellar`, `abrir`, `vencido`), `MensajePublico`, `Buzon` con TTL |
| `nodo.py` | `Nodo` (ciclo de vida, `enviar_celda`, `construir_circuito`, `enviar_mensaje`, `crear_tema_privado`, `enviar_tema`, `publicar`, `panico`), `Tramo` (estado de un relé: solo anterior y siguiente) y `Circuito` (lado cliente) |
| `cli.py` | Cliente de terminal con parámetros por línea de comandos |

## 4.4 Gateway (`gateway/faronet_gateway/`)

| Elemento | Descripción |
|---|---|
| `Puente` (`puente.py`) | Se engancha al nodo gateway: publica los `MensajePublico` que llegan como salida de circuito y sube el directorio cada 5 min |
| `ClienteEdge` (`edge.py`) | Cliente HTTPS firmado del Worker: `publicar`, `subir_directorio`, `directorio`, `mensajes` |
| `id_buzon`, `sellar_buzon`, `abrir_buzon`, `depositar`, `retirar` | Buzón muerto: identificador y llave derivados del secreto compartido |

## 4.5 Worker (`worker/src/`)

| Archivo | Contenido |
|---|---|
| `index.ts` | Enrutador HTTP: páginas, API pública, buzón y rutas firmadas del gateway |
| `seguridad.ts` | `autenticarGateway` (firma, ventana de 60 s, anti-replay) y `permitir` (rate limiting con hash) |
| `sala.ts` | Durable Object `Sala`: WebSockets hibernables, historial en SQLite, `feedAtom` |
| `central.ts` | Durable Object `Central`: directorio verificado, salas activas y último tiempo por gateway |
| `buzon.ts` | Durable Object `Buzon`: blobs de 1024 B con TTL y lectura única |
| `paginas.ts` | HTML de inicio y de sala con CSP por nonce |
| `util.ts` | hex/base64, `sha256`, `verificarEd25519` (WebCrypto), respuestas JSON |

# 5. Instrucciones para ejecutar

## 5.1 Compilar y flashear el Faro

```bash
arduino-cli core install arduino:avr
# Arduino Uno
arduino-cli compile --fqbn arduino:avr:uno firmware/faro
arduino-cli upload  --fqbn arduino:avr:uno -p /dev/ttyACM0 firmware/faro   # clones CH340: /dev/ttyUSB0
# Arduino Nano (clon CH340)
arduino-cli compile --fqbn arduino:avr:nano firmware/faro
arduino-cli upload  --fqbn arduino:avr:nano:cpu=atmega328old -p /dev/ttyUSB0 firmware/faro
```

Si no hay permiso sobre el puerto: `sudo usermod -aG dialout $USER` y volver a
iniciar sesión. Pruebas del núcleo en la PC:

```bash
cd firmware/faro/test
g++ -std=c++11 -Wall -I.. test_core.cpp ../faro_core.cpp -o test_core && ./test_core
```

## 5.2 Instalar la biblioteca, el nodo y el gateway

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e adaptador -e nodo -e gateway      # desde la raíz del repositorio
```

## 5.3 Probar el Faro

```bash
faro -p /dev/ttyACM0 info
faro -p /dev/ttyACM0 sondear --continuo           # A0 y comparador
faro -p /dev/ttyACM0 enviar a1:b2:c3:d4 "hola"
faro -p /dev/ttyACM0 escuchar
faro -p /dev/ttyACM0 direccion --rotar
faro -p /dev/ttyACM0 configurar --bps 4000        # igual en los dos Faros

# Tasa efectiva y BER (una distancia por corrida)
faro -p /dev/ttyACM0 medir receptor --tramas 200 --tam 114 --distancia 1m --csv hardware/mediciones.csv
faro -p /dev/ttyUSB1 medir emisor   --tramas 200 --tam 114
```

Solo un programa a la vez puede usar el puerto serial, y cada vez que se abre
el puerto el Uno se reinicia.

## 5.4 Ejecutar los nodos

```bash
# Nodo con identidad en archivo, escuchando y conectado a un vecino
faronet --llave ana.key --nombre ana --escuchar 0.0.0.0:9101 --vecino 192.168.1.20:9101

# Nodo con Faro: la identidad vive en la EEPROM y el pánico la borra
faronet --faro /dev/ttyACM0 --nombre puente-sur --escuchar 0.0.0.0:9101

# Gateway conectado al Worker
faronet --llave gw.key --nombre gw-norte --gateway \
        --edge https://faronet.faronet-worker.workers.dev --escuchar 0.0.0.0:9101

# Relé sin consola
faronet --llave rele.key --escuchar 0.0.0.0:9101 --vecino 10.0.0.5:9101 --sin-consola
```

Comandos de la consola: `nodos`, `rutas`, `circuitos`, `enviar <nombre|id> <texto>`,
`publicar <tema> <texto>`, `tema crear|enviar|ver`, `buzon`, `panico`, `salir`.
Demo local con 5 relés: `nodo/demo_local.sh`.

## 5.5 Desplegar el Worker

```bash
cd worker
npm install
npx wrangler login                                # una vez
faronet-edge llave --llave ~/llaves/gateway.key   # llave pública para GATEWAYS en wrangler.toml
npx wrangler deploy
```

Desarrollo local sin cuenta: `npx wrangler dev --var GATEWAYS:<llave_publica_hex>`.

## 5.6 Usar el edge desde la terminal

```bash
faronet-edge --url https://faronet.faronet-worker.workers.dev directorio
S=$(faronet-edge buzon secreto)
faronet-edge --url https://faronet.faronet-worker.workers.dev buzon depositar "$S" "nos vemos en el faro norte"
faronet-edge --url https://faronet.faronet-worker.workers.dev buzon retirar "$S"
```

Salas en el navegador: `https://faronet.faronet-worker.workers.dev/salas/general`
y su feed en `/salas/general/feed.xml`.

## 5.7 Pruebas automáticas

```bash
cd adaptador && python -m unittest -v     # 22 pruebas (1 se salta sin g++/Scapy)
cd nodo      && python -m unittest -v     # 28 pruebas
cd gateway   && python -m unittest -v     # integración contra wrangler dev
```

# 6. Actividades realizadas por estudiante

**[PENDIENTE]** Cada integrante debe completar las horas a partir de su
bitácora. Las actividades y fechas de abajo salen del historial de Git y de
las sesiones de trabajo registradas; las horas están en blanco a propósito.

## David Zamora

| Fecha | Actividad | Horas |
|---|---|---|
| 2026-09-30 | Documento de kick-off y estructura del repositorio | |
| 2026-10-15 a 2026-11-01 | Revisión y fusión de los PR #1 a #8 | |
| 2026-10-26 | Estudio de la guía de armado del Faro en protoboard | |
| 2026-10-31 | Armado del Faro en protoboard (Uno R3), pruebas 2 a 7 del receptor y emisor | |
| 2026-10-31 | Preparación de la Raspberry Pi 2 como nodo `faronet-sur` | |
| 2026-11-01 | Soldadura del Faro 2 en placa perforada: etapa 3A (rieles de 5 V y GND) y pruebas de corto | |
| 2026-11-01 a 2026-11-02 | Soldadura: etapas 3B (divisor de umbral) y 3C (receptor) | |
| | ... | |
| | **Total** | |

## Diego Zamora

| Fecha | Actividad | Horas |
|---|---|---|
| 2026-10-15 | Firmware del Faro y biblioteca DispositivoLuzAdaptador (Capa 1), CI | |
| 2026-10-17 | Mesh FaroNet: circuitos onion, ruteo dinámico, directorio firmado | |
| 2026-10-17 | Worker en el edge: salas, feeds, buzón muerto, directorio | |
| 2026-10-17 | Puente mesh → edge en el gateway | |
| 2026-10-20 | Faro en protoboard y calibración del receptor (`calibrar_receptor.py`) | |
| 2026-11-01 | Despliegue del Worker en Cloudflare y prueba de punta a punta | |
| 2026-11-01 | RFC de FaroNet y temas privados | |
| | ... | |
| | **Total** | |

# 7. Autoevaluación

## 7.1 Estado final

| Componente | Estado al 2 de noviembre de 2026 |
|---|---|
| Firmware del Faro | Completo; compila para Nano y Uno; núcleo probado en la PC |
| Biblioteca DispositivoLuzAdaptador | Completa, con simulador, Scapy y comandos de medición; 22 pruebas pasan |
| Faro en protoboard | Funciona por separado en ambos Faros (recepción con LED propio y hoja / frente a frente) |
| Faro soldado | En curso (Faro de David: etapas 3A–3B listas, 3C en curso, falta emisor) |
| Prueba Faro contra Faro | **[PENDIENTE]** |
| Tasa efectiva y BER a 3 distancias | **[PENDIENTE]** (procedimiento y herramienta listos: `faro medir`) |
| Esquemático KiCad, fotos, bitácora de multímetro | **[PENDIENTE]** (esquemático y netlist en Markdown sí existen) |
| Mesh: ruteo, directorio, onion, mensajes privados, temas privados | Completa; 28 pruebas pasan (incluye red de 6 nodos y red que cruza dos Faros simulados) |
| Autenticación de `HOLA` y tráfico de relleno | **[PENDIENTE]** |
| Gateway y Worker | Completos y desplegados en <https://faronet.faronet-worker.workers.dev> |
| RFC | Completo (`docs/rfc-faronet.txt`); falta llenar la tabla de mediciones del Apéndice B |

## 7.2 Problemas encontrados y limitaciones

* El trimpot del kit no variaba el voltaje: se reemplazó por un divisor fijo.
* El sensor del Faro de David es débil (probablemente un fotodiodo y no un
  fototransistor): el margen entre luz y oscuridad es justo para 1–2 m.
* Abrir el puerto serial reinicia el Uno y solo un programa puede usarlo a
  la vez; cambiar piezas con el USB conectado llegó a tumbar la Raspberry Pi.
* Faltaban valores de resistencia (1 MΩ, 4,7 kΩ, 10 kΩ) y se usaron
  equivalentes o combinaciones en paralelo.
* La placa perforada usada tiene la numeración de columnas invertida entre
  la cara de cobre y la de componentes, lo que obligó a rehacer los mapas.
* Limitaciones de diseño: enlaces entre vecinos sin cifrar, `HOLA` sin
  autenticar, sin tráfico de cobertura, sin defensa contra Sybil (sección 3.6).

## 7.3 Reporte de commits

Generado con `git log --date=short --format='%h %ad %an %s'` sobre `main`:

| Commit | Fecha | Autor | Descripción |
|---|---|---|---|
| `b1d3ada` | 2026-11-01 | DavidZamoraB | Merge PR #8 (temas privados) |
| `21ae6d2` | 2026-11-01 | DavidZamoraB | Merge PR #7 (RFC) |
| `27757fc` | 2026-11-01 | Diego Zamora | RFC: sección 5.3 Temas privados |
| `1a20a88` | 2026-11-01 | Diego Zamora | Temas privados: residen únicamente dentro de FaroNet |
| `679f5ed` | 2026-11-01 | Diego Zamora | RFC de FaroNet: Capa 1, mesh anónima y edge |
| `5ccc60f` | 2026-11-01 | DavidZamoraB | Merge PR #6 (despliegue del Worker) |
| `a68638c` | 2026-11-01 | Diego Zamora | Worker desplegado en Cloudflare |
| `f5fee32` | 2026-10-31 | DavidZamoraB | Merge PR #5 (hardware del receptor) |
| `76f0070` | 2026-10-24 | Claude | Hardware: receptor probado por Diego |
| `14363c7` | 2026-10-17 | DavidZamoraB | Merge PR #4 (puente edge) |
| `337acee` | 2026-10-17 | Diego Zamora | Puente mesh → edge |
| `60b89eb` | 2026-10-17 | DavidZamoraB | Merge PR #2 (mesh onion) |
| `f78d7ff` | 2026-10-17 | Diego Zamora | Worker en el edge (Capa 7) |
| `e0deafa` | 2026-10-17 | Diego Zamora | Mesh FaroNet (Capas 2, 3 y 7) |
| `718f878` | 2026-10-15 | Diego Zamora Bustos | Merge PR #1 (Capa 1) |
| `2af63c3` | 2026-10-15 | Diego Zamora | CI: pruebas y compilación del firmware |
| `07cc883` | 2026-10-15 | Diego Zamora | Faro: hardware, firmware y biblioteca (Capa 1) |
| `8dfa32a` | 2026-09-30 | DavidZamoraB | docs: actualizar documento de kick-off |
| `569ea44` | 2026-10-01 | Equipo FaroNet | Estructura inicial del repositorio |

Antes de entregar se debe regenerar esta tabla con el historial final.

## 7.4 Calificación según la rúbrica

**[PENDIENTE]** Cada ítem de 0 a 10, a llenar por el equipo.

| Rubro | Peso | Nota (0–10) |
|---|---|---|
| Hardware: Faro soldado (esquemático, BOM, soldadura, pruebas) | 25 % | |
| Capa 1: protocolo físico y DispositivoLuzAdaptador | 10 % | |
| Capas 2 y 3: mesh anónima y directorio de nodos | 15 % | |
| Privacidad: modelo de amenazas, cifrado, padding, pánico | 10 % | |
| Capa 7: aplicación anónima a través de FaroNet | 5 % | |
| Capa 7: aplicación pública en el edge | 25 % | |
| RFC | 5 % | |
| Documentación | 5 % | |
| Kick-off | 5 % extra | |
| Extra: mayor tasa de transferencia | 10 % | |

## 7.5 Autoevaluación de aprendizaje

**[PENDIENTE]** Escala [1] Muy malo, [2] Malo, [3] Regular, [4] Bueno, [5] Muy bueno.

| Rubro | David | Diego |
|---|---|---|
| Aprendizaje de soldadura y hardware | | |
| Aprendizaje de la capa física | | |
| Aprendizaje de enrutamiento en redes mesh | | |
| Aprendizaje de privacidad y anonimato | | |
| Aprendizaje de serverless en el edge | | |
| Aprendizaje de redacción de RFCs | | |

# 8. Lecciones aprendidas

Para quien lleve este curso en el futuro:

1. **Empiecen por el hardware.** El software se puede escribir y probar con
   un simulador, pero el hardware depende de comprar piezas, de que las
   piezas sirvan y de aprender a soldar. Fue el cuello de botella.
2. **Compren repuestos y verifiquen el sensor.** Un "fototransistor" de
   tienda puede ser un fotodiodo con mucha menos corriente. Prueben cada
   pieza en protoboard antes de soldarla y compren con filtro de luz diurna.
3. **Prefieran valores fijos a trimpots baratos.** Un divisor de dos
   resistencias es más estable y más fácil de reproducir.
4. **Midan antes de energizar.** La prueba de continuidad entre +5 V y GND
   evita quemar el Arduino o el puerto USB de la computadora. No cambien
   piezas con el USB conectado.
5. **Dibujen la placa por la cara en la que van a soldar.** La placa
   perforada se ve en espejo desde el cobre; un mapa con la orientación
   equivocada cuesta horas.
6. **Hagan el protocolo independiente del hardware.** Separar el núcleo del
   firmware (`faro_core`) permitió probarlo en la PC con desfase de reloj y
   ruido simulados.
7. **Tamaño fijo en todo.** Celdas, sobres y blobs de tamaño fijo resuelven
   el padding de una vez y simplifican el análisis de privacidad.
8. **No inventen criptografía.** Con libsodium y WebCrypto basta; el trabajo
   real es el diseño del protocolo y el modelo de amenazas.
9. **Ramas, pull requests y CI desde el día uno.** Cada PR corrió las pruebas
   y compiló el firmware; `main` nunca quedó roto.
10. **El plan gratuito de Cloudflare alcanza**, pero solo con Durable
    Objects SQLite; revisen las limitaciones del plan antes de diseñar.

# 9. Bibliografía

* Bradner, S. *Key words for use in RFCs to Indicate Requirement Levels*. RFC 2119, 1997.
* Leiba, B. *Ambiguity of Uppercase vs Lowercase in RFC 2119 Key Words*. RFC 8174, 2017.
* Flanagan, H. y Ginoza, S. *RFC Style Guide*. RFC 7322, 2014.
* Cooper, A. et al. *Privacy Considerations for Internet Protocols*. RFC 6973, 2013.
* Fielding, R., Nottingham, M. y Reschke, J. *HTTP Semantics*. RFC 9110, 2022.
* Hedrick, C. *Routing Information Protocol*. RFC 1058, 1988.
* Josefsson, S. y Liusvaara, I. *Edwards-Curve Digital Signature Algorithm (EdDSA)*. RFC 8032, 2017.
* Langley, A., Hamburg, M. y Turner, S. *Elliptic Curves for Security*. RFC 7748, 2016.
* Saarinen, M-J. y Aumasson, J-P. *The BLAKE2 Cryptographic Hash and MAC*. RFC 7693, 2015.
* Nottingham, M. y Sayre, R. *The Atom Syndication Format*. RFC 4287, 2005.
* Arciszewski, S. *XChaCha: eXtended-nonce ChaCha and AEAD_XChaCha20_Poly1305*. draft-irtf-cfrg-xchacha, 2020.
* Dingledine, R., Mathewson, N. y Syverson, P. *Tor: The Second-Generation Onion Router*. USENIX Security, 2004.
* Goldberg, I., Stebila, D. y Ustaoglu, B. *Anonymity and one-way authentication in key exchange protocols*. Designs, Codes and Cryptography, 2013.
* Cheshire, S. y Baker, M. *Consistent Overhead Byte Stuffing*. IEEE/ACM Transactions on Networking, 1999.
* IEEE 802.3. *Codificación Manchester* (cláusula 7, 10BASE).
* libsodium. *Documentation*. <https://doc.libsodium.org>
* PyNaCl. *Documentation*. <https://pynacl.readthedocs.io>
* Cloudflare. *Workers, Durable Objects y Rate Limiting*. <https://developers.cloudflare.com/workers/>
* Arduino. *Language Reference* y *arduino-cli*. <https://docs.arduino.cc>
* Texas Instruments. *LM393 Dual Comparator Datasheet*.
* Moraga, K. *Proyecto 1: FaroNet*. Enunciado del curso Redes de Computadoras, ITCR, 2026.

# 10. Documentación del código fuente

El código está documentado en el propio repositorio:

* Cada carpeta tiene un `README.md` con propósito, instalación, uso y diseño
  (`firmware/`, `adaptador/`, `nodo/`, `gateway/`, `worker/`, `hardware/`).
* Cada módulo Python empieza con un docstring que explica el formato que
  implementa (por ejemplo `nodo/faronet/onion.py` explica la aritmética de
  las capas y `nodo/faronet/mensaje.py` el formato del sobre).
* El firmware comenta cada bloque (`faro_core.h` documenta el decodificador
  Manchester y sus estados).
* El Worker comenta en cada archivo las decisiones de seguridad y no registro.
* `docs/capa1-protocolo.md` y el RFC especifican los formatos byte a byte.

# Anexo: RFC de FaroNet

El RFC completo (`docs/rfc-faronet.txt`) se adjunta a continuación en su
formato ASCII original.
