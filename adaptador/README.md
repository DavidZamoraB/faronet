# adaptador

Biblioteca **DispositivoLuzAdaptador**: comunicación entre la computadora del
nodo y el Faro por USB-serial. Es lo único que la mesh (`nodo/`, `gateway/`)
necesita para usar la luz como interfaz de red.

## Instalación

```bash
cd adaptador
python3 -m venv .venv && source .venv/bin/activate
pip install -e .            # o: pip install -e '.[scapy]'
```

Queda disponible el comando `faro` (equivalente a `python -m dispositivo_luz_adaptador`).

## Uso desde Python

```python
from dispositivo_luz_adaptador import DispositivoLuzAdaptador, DIFUSION

with DispositivoLuzAdaptador("/dev/ttyUSB0") as faro:
    print(faro.info())                       # dirección, bps, opciones
    faro.al_panico(lambda nueva: borrar_llaves_del_nodo())

    r = faro.enviar("a1:b2:c3:d4", b"hola")  # unicast con ACK y reintentos
    print(r.ok, r.intentos)
    faro.enviar(DIFUSION, b"a todos")         # difusión, sin ACK

    rec = faro.recibir(timeout=5)            # TramaRecibida o None
    if rec and rec.crc_ok:
        print(rec.trama.origen, rec.trama.carga)

    faro.rotacion_automatica(cada_segundos=600)   # privacidad: dirección rotable
```

* `MTU = 114` bytes de carga por trama. Fragmentar arriba si hace falta.
* `al_recibir(callback)` como alternativa a `recibir()`; el callback corre en el
  hilo lector.
* `enviar_trama(Trama | bytes)` transmite una trama armada fuera del Faro
  (p. ej. con `scapy_faro.FaroTrama`), tal cual, incluso con CRC malo.
* `guardar_secreto(32 bytes)` / `leer_secreto()`: un espacio en la EEPROM del
  Faro que el botón de pánico borra. Pensado para la llave privada del nodo.
* `configurar(bps=..., promiscuo=..., entregar_crc_malo=..., reintentos=...)`.
  **Los dos Faros deben usar los mismos bps.**

## Desarrollar sin hardware

`simulador.py` imita el firmware y une varios Faros por un medio con BER
configurable. La mesh se puede programar y probar sin tener los Faros soldados:

```python
from dispositivo_luz_adaptador import DispositivoLuzAdaptador
from dispositivo_luz_adaptador.simulador import FaroSimulado, MedioSimulado

medio = MedioSimulado(ber=1e-4)
a = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
b = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
a.enviar(b.direccion, b"hola")
print(b.recibir(timeout=1).trama.carga)
```

## Cliente de terminal

```bash
faro -p /dev/ttyUSB0 info
faro -p /dev/ttyUSB0 enviar a1:b2:c3:d4 "hola"
faro -p /dev/ttyUSB0 enviar difusion "hola a todos" --sin-ack
faro -p /dev/ttyUSB0 escuchar [--promiscuo]
faro -p /dev/ttyUSB0 configurar --bps 4000 --reintentos 3
faro -p /dev/ttyUSB0 direccion --rotar
faro -p /dev/ttyUSB0 secreto --generar
faro -p /dev/ttyUSB0 panico
faro -p /dev/ttyUSB0 sondear --continuo          # calibrar el trimpot
faro -p /dev/ttyUSB0 emisor encender|apagar      # LED IR fijo, para el multímetro
faro -p /dev/ttyUSB0 medir receptor --tramas 200 --distancia 1m --csv mediciones.csv
faro -p /dev/ttyUSB1 medir emisor   --tramas 200
```

## Pruebas

```bash
cd adaptador && python3 -m unittest -v
```

Incluyen: formato de trama, CRC, COBS, comandos contra Faros simulados (ACK,
difusión, promiscuo, pánico, rotación), medición de BER con ruido, que las
constantes coincidan con las del firmware, y las pruebas en C++ del firmware.
