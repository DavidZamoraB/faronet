# Capa 1 del Faro: especificación (borrador para el RFC)

Describe lo implementado en `firmware/faro` y `adaptador/`. Las palabras DEBE,
NO DEBE, PUEDE siguen el sentido de RFC 2119.

## 1. Medio y codificación de línea

* Medio: luz infrarroja de 940 nm. LED encendido / apagado (OOK) con
  **codificación Manchester** según IEEE 802.3:
  `0` = encendido→apagado y `1` = apagado→encendido, con la transición a mitad
  de bit.
* En reposo el LED está apagado.
* Velocidad configurable de 500 a 20 000 bit/s, 2 000 bit/s por defecto. Los
  dos extremos DEBEN usar la misma velocidad.

Por qué Manchester y no OOK simple:

1. **Auto-sincronizante**: siempre hay un flanco a mitad de bit, así que el
   receptor corrige el desfase entre los relojes de los dos Arduinos en cada
   bit. El decodificador tolera ±50 % de error en cada intervalo (probado con
   ±8 % de desfase de reloj).
2. **Balance de continua**: la mitad del tiempo hay luz. El nivel promedio es
   constante, lo que facilita fijar el umbral del comparador.
3. **Detección de errores de línea**: un intervalo que no es ni medio bit ni
   un bit completo es imposible en Manchester. El receptor descarta la trama
   en curso sin esperar al CRC.

El costo es duplicar el ancho de banda (2 baudios por bit), aceptable para
el fototransistor a estas velocidades.

## 2. Sincronización

```
 +----------------------+---------+--------------------------------+
 | Preámbulo 4 x 0x55   | SFD     |  Trama (14 a 128 bytes)        |
 | 01010101 ...         | 0xD5    |                                |
 +----------------------+---------+--------------------------------+
```

* El preámbulo `0x55` en Manchester produce solo intervalos de un bit
  completo. Tras 8 seguidos el receptor sabe que cada flanco cae a mitad de
  bit y empieza a leer bits.
* El SFD `0xD5` rompe la alternancia. El receptor busca el patrón de 16 bits
  `0x55D5`. Si encuentra `0xAA2A` (el patrón negado), la señal llega
  invertida, por ejemplo porque el comparador está cableado al revés. En ese
  caso invierte los bits siguientes, de modo que la polaridad del hardware no
  importa.
* Los bytes se transmiten con el bit más significativo primero.
* El preámbulo y el SFD **no** cuentan dentro de los 128 bytes de la trama.

## 3. Formato de la trama (versión 1)

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

| Campo | Bytes | Descripción |
|---|---|---|
| VERSION | 1 | `0x01`. Un receptor DEBE descartar tramas de versiones que no conoce (el nodo PUEDE verlas en modo promiscuo). |
| LON | 1 | Longitud de la CARGA. Es el campo aparte que define el tamaño del único campo dinámico. |
| BANDERAS | 4 bits | bit 0 (`0x10` del byte): PIDE_ACK. Los demás son reservados y valen 0. |
| TIPO | 4 bits | `0` = DATOS, `1` = ACK. Los demás valores quedan reservados. |
| SEQ | 1 | Número de secuencia. El ACK repite el SEQ de la trama que confirma. |
| DESTINO | 4 | Dirección física destino. `FF:FF:FF:FF` = difusión. |
| ORIGEN | 4 | Dirección física de quien transmite. |
| CARGA | LON | Datos de la capa superior (FaroNet). Máximo 114 bytes. |
| CRC-16 | 2 | CRC-16/CCITT-FALSE (polinomio `0x1021`, valor inicial `0xFFFF`, sin reflejar), big-endian, sobre todos los bytes anteriores. |

**Regla de versionado.** En toda versión futura VERSION y LON DEBEN seguir
siendo los bytes 0 y 1, y la trama DEBE medir `12 + LON + 2` bytes. Así
cualquier receptor sabe dónde termina una trama aunque no entienda su
versión, y una versión nueva puede redefinir los bytes 2 a 11 o usar la carga
para cabeceras extendidas.

**Tramas armadas fuera del Faro.** El nodo puede entregar una trama completa
(por ejemplo construida con Scapy, `adaptador/dispositivo_luz_adaptador/scapy_faro.py`).
El Faro solo verifica que su longitud sea coherente con LON y la transmite tal
cual, sin recalcular el CRC.

## 4. Direcciones físicas

* 4 bytes, guardados en la EEPROM del Faro. `00:00:00:00` y `FF:FF:FF:FF`
  no son válidas como dirección propia.
* **Rotables**: el nodo genera una nueva con el generador criptográfico del
  sistema operativo (`os.urandom`) y la fija en el Faro. La biblioteca ofrece
  rotación periódica con ±20 % de variación aleatoria en el intervalo.
* Con 4 bytes hay 2³² direcciones. En una red de decenas de Faros, la
  probabilidad de que dos direcciones aleatorias choquen es despreciable
  (≈ n²/2³³), y cada trama ahorra 4 bytes frente a usar 6 como Ethernet.

## 5. Acceso al medio: CSMA/CA con ACK

El canal es semidúplex y un Faro no puede escuchar mientras transmite, así que
no hay detección de colisiones. Las colisiones se evitan con:

1. **Escucha de portadora**: el canal está ocupado si el decodificador está
   dentro de una trama o si ve intervalos Manchester válidos seguidos. El
   ruido de la luz ambiental no forma esos intervalos, así que no bloquea el
   canal.
2. **Espera aleatoria** de 0 a `ventana − 1` ranuras (1 ranura = 24 bits).
   La ventana empieza en 8 y se duplica en cada reintento, hasta 64.
3. **DIFS**: el canal debe estar libre durante 32 bits seguidos antes de
   transmitir. Si en 3 s nunca queda libre, se reporta `CANAL_OCUPADO`.
4. **ACK**: una trama unicast con PIDE_ACK se confirma con una trama TIPO=ACK
   (sin carga, 14 bytes). El receptor la envía tras un **SIFS** de 12 bits sin
   escuchar el canal: como SIFS < DIFS, el ACK tiene prioridad sobre cualquier
   otra transmisión.
5. Si el ACK no llega en `SIFS + 48 bits + tiempo de un ACK`, se retransmite,
   hasta `reintentos` veces (3 por defecto, configurable de 0 a 7).
6. El receptor recuerda los últimos 8 pares (origen, SEQ). Si el ACK se
   perdió y llega una retransmisión, la vuelve a confirmar pero no la entrega
   dos veces al nodo.

Las tramas de difusión nunca piden ACK.

## 6. Protocolo nodo ↔ Faro (USB-serial)

* 115 200 baudios, 8N1.
* Cada paquete: `COBS(TIPO | DATOS | CRC-16) || 0x00`. COBS elimina los bytes
  `0x00` del contenido, así que `0x00` marca sin ambigüedad el fin del
  paquete y el receptor se resincroniza tras cualquier basura en la línea.
* Un comando a la vez: el nodo espera la respuesta antes de enviar el
  siguiente. Los eventos (`TRAMA_RECIBIDA`, `PANICO`) pueden llegar en
  cualquier momento.

| Código | Comando (nodo → Faro) | Datos | Respuesta |
|---|---|---|---|
| 0x01 | PING | — | 0x81 PONG: fw mayor, fw menor, versión protocolo, máx. trama |
| 0x02 | INFO | — | 0x82 INFO: dirección(4), bps(2), opciones, reintentos, ¿secreto? |
| 0x03 | ENVIAR | destino(4), banderas, carga | 0x83 RESULTADO_TX: estado, intentos, SEQ |
| 0x04 | ENVIAR_CRUDA | trama completa | 0x83 RESULTADO_TX |
| 0x05 | FIJAR_DIRECCION | dirección(4) | 0x85 DIRECCION |
| 0x06 | ROTAR_DIRECCION | — | 0x85 DIRECCION |
| 0x07 | CONFIGURAR | bps(2), opciones, reintentos | 0x82 INFO |
| 0x08 / 0x09 | ESTADISTICAS / REINICIAR | — | 0x88: 6 × uint32 |
| 0x0A | GUARDAR_SECRETO | 32 bytes | 0x8A |
| 0x0B | LEER_SECRETO | — | 0x8B secreto(32) |
| 0x0C | PANICO | — | evento 0x8C |
| 0x0D | SONDEAR | — | 0x8D: analógico(2), digital(1) |
| 0x0E | EMISOR_FIJO | 0/1 | 0x8D |

Eventos: `0x90 TRAMA_RECIBIDA` (crc_ok, trama) y `0x8C PANICO` (nueva
dirección). Error: `0xFF` + código (1 comando desconocido, 2 longitud,
3 CRC del enlace, 4 parámetro, 5 sin secreto).

Estados de transmisión: 0 OK, 1 SIN_ACK, 2 CANAL_OCUPADO, 3 TRAMA_INVALIDA,
4 ABORTADO_PANICO. Opciones: bit 0 = promiscuo, bit 1 = entregar tramas con
CRC malo (para medir BER).

## 7. Consideraciones de privacidad

* Un **observador del medio físico** ve cuándo hay transmisión, el tamaño de
  cada trama y las direcciones físicas, que van en claro. No ve el contenido
  si la capa superior cifra de extremo a extremo.
  * Mitigación: rotar las direcciones físicas; la capa FaroNet rellena
    (padding) a tamaño fijo, de modo que LON sea constante.
* El Faro **no guarda registros**: las estadísticas son solo contadores y la
  tabla de duplicados (8 entradas) vive en RAM y se sobrescribe sola.
* **Botón de pánico**: sobrescribe el secreto en EEPROM (primero `0xFF`,
  luego `0x00`), genera una dirección nueva, borra buffers, estadísticas y
  la tabla de duplicados, y avisa al nodo para que borre sus propias llaves.
* La dirección generada por el propio Faro tras un pánico usa un generador
  no criptográfico (xorshift con semilla de ruido analógico). Eso basta para
  romper la asociación con la dirección anterior. Las rotaciones normales
  las hace el nodo con `os.urandom`.

## 8. Consideraciones de seguridad

* El CRC detecta errores accidentales, no manipulación: cualquiera con un LED
  IR puede inyectar tramas válidas con cualquier dirección de origen. La
  autenticidad DEBE resolverse en FaroNet (firmas y cifrado autenticado).
* Un atacante puede saturar el canal con luz modulada (negación de servicio)
  y el Faro reportará `CANAL_OCUPADO`. No hay mitigación en la Capa 1.
* `LEER_SECRETO` entrega el secreto a quien tenga acceso al puerto USB. Se
  asume que el nodo conectado es de confianza. El secreto protege contra el
  robo del Faro *después* de presionar el pánico, no antes.
