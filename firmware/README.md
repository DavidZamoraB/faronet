# firmware

Firmware del Faro para **Arduino Nano** (ATmega328P; también compila para Uno).

| Archivo | Contenido |
| --- | --- |
| `faro/faro.ino` | Hardware: emisión Manchester, interrupción de recepción, MAC (CSMA + ACK), EEPROM, pánico, comandos del nodo |
| `faro/faro_core.h/.cpp` | Lógica sin hardware: formato de trama, CRC-16, COBS, decodificador Manchester |
| `faro/enlace_serial.h` | Códigos del protocolo nodo ↔ Faro por USB-serial |
| `faro/test/test_core.cpp` | Pruebas del núcleo en la PC (no se compila en el Arduino) |

El protocolo está descrito en [../docs/capa1-protocolo.md](../docs/capa1-protocolo.md).

## Compilar y cargar

Con Arduino IDE: abrir `faro/faro.ino`, placa **Arduino Nano**. Los clones con
CH340 suelen necesitar el procesador **ATmega328P (Old Bootloader)**.

Con `arduino-cli`:

```bash
arduino-cli core install arduino:avr
arduino-cli compile --fqbn arduino:avr:nano firmware/faro
arduino-cli upload  --fqbn arduino:avr:nano:cpu=atmega328old -p /dev/ttyUSB0 firmware/faro
```

(Si el upload falla con `not in sync`, probar `--fqbn arduino:avr:nano` sin `cpu=`.)

En Linux, si no hay permiso sobre `/dev/ttyUSB0`: `sudo usermod -aG dialout $USER`
y volver a iniciar sesión.

## Probar el núcleo sin Arduino

```bash
cd firmware/faro/test
g++ -std=c++11 -Wall -I.. test_core.cpp ../faro_core.cpp -o test_core && ./test_core
```

Simula la forma de onda en la luz (con desfase de reloj de ±8 %, ruido de
temporización y señal invertida) y verifica que el decodificador recupere cada
trama.

## Pines

| Pin Nano | Función |
| --- | --- |
| D2 | Entrada del comparador (INT0) |
| D3 | Botón de pánico a GND (pull-up interno) |
| D4 | Base del transistor del LED IR (vía 1 kΩ) |
| D5 / D6 / D7 | LED TX / LED RX / LED estado-pánico |
| A0 | Voltaje del fototransistor (solo calibración) |

## Comportamiento visible

* Al encender: los tres LEDs se encienden en secuencia.
* LED TX encendido mientras se transmite; LED RX parpadea con cada trama.
* Botón de pánico (mantener 50 ms): borra el secreto de la EEPROM, cambia la
  dirección física, limpia buffers y estadísticas, avisa al nodo y parpadea;
  al final el LED rojo queda encendido hasta reiniciar.
