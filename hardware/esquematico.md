# Esquemático del Faro

Este documento es la referencia para dibujar el esquemático en KiCad (entregable)
y para soldar. Todo el circuito funciona a 5 V tomados del pin `5V` del Arduino
Nano, que a su vez se alimenta por el USB del nodo.

**Versión probada.** Los valores del receptor son los del Faro de Diego, que
funcionó en protoboard el 20-10-2026 (sensor ≈ 55 apagado y ≈ 272 encendido en
A0, comparador 0 → 1 estable). Respecto al diseño original cambian R4
(1 MΩ → 1,5 MΩ), R5 (4,7 kΩ → 10 kΩ) y el umbral: el trimpot RV1 se reemplazó por
un divisor fijo R9/R10, porque el trimpot del kit no variaba el voltaje.

**Placa.** Sirve un Arduino **Nano o Uno**: el firmware compila para los dos y
los pines D2–D7 y A0 son los mismos. Un Pro Mini también sirve si es la versión
de 5 V / 16 MHz (cristal "16.000"), pero no tiene USB: necesita un adaptador
USB-serial (FTDI, CP2102 o CH340) en sus 6 pines de programación.

**La Raspberry Pi no reemplaza al Arduino.** La Pi es el *nodo*: corre
`faronet` y se conecta al Faro por USB. Sus GPIO son de 3,3 V y Linux no da la
precisión de tiempos que necesita Manchester.

## Bloques

```
                +----------------------------------------------+
   USB (nodo) ==|  Arduino Nano                                |
                |                                              |
                |  D4 ----> [ Emisor: 2N2222A + LED IR ]  ~~~> luz
                |                                              |
   luz ~~~>  [ Receptor: fototransistor -> LM393 ] ----> D2    |
                |              \--------------------> A0      |
                |                                              |
                |  D5 -> LED TX    D6 -> LED RX    D7 -> LED   |
                |  D3 <- botón de pánico                       |
                +----------------------------------------------+
```

## 1. Emisor (LED IR con transistor como interruptor)

```
              +5V
               |
              [R1] 82 Ω  1/4 W
               |
               +---|>|---+        LED1: LED IR 940 nm (pata larga = ánodo)
                  A    K |
                         |
                         C
   D4 ---[R2 1 kΩ]---- B   Q1  2N2222A (NPN)
                         E
                         |
                        GND
```

* Corriente del LED: `(5 V − 1,2 V (Vf LED IR) − 0,2 V (Vce sat)) / 82 Ω ≈ 44 mA`.
  El LED IR típico aguanta 100 mA continuos, así que hay margen.
* Potencia en R1: `0,044² × 82 ≈ 0,16 W` aun si el LED quedara encendido fijo
  (< 0,25 W de una resistencia de 1/4 W).
* Corriente de base: `(5 − 0,7) / 1 kΩ ≈ 4,3 mA`. Con β forzado ≈ 10 el
  transistor queda saturado (44 mA / 4,3 mA ≈ 10). El pin del Arduino da 4,3 mA,
  muy por debajo de su límite de 20 mA.
* ¿Por qué transistor? El pin del Nano no debe entregar 44 mA; además el
  transistor permite subir la corriente (más alcance) sin tocar el Arduino.
* Si consiguen solo 100 Ω en lugar de 82 Ω: ≈ 36 mA, funciona igual con algo
  menos de alcance.

## 2. Receptor (fototransistor + comparador LM393)

```
        +5V
         |
         C
     Q2  fototransistor IR
         E                                          +5V
         |                                           |
         |  SENSOR                                 [R5] 10 kΩ
         +--------+-----------+                      |
         |        |           |   pin3 |\            |
       [R3]       |           +--------|+ \   pin1   |
       10 kΩ      |                    |   >---------+---------> D2 (INT0)
         |        |           +--------|- /          |
        GND       |           |   pin2 |/  U1 LM393  |
                  |           |                      |
                  |           |    +5V               |
                  |           |     |                |
                  |           |   [R9] 10 kΩ         |
                  |           |     |                |
                  |           +-----+ UMBRAL ≈ 0,45 V|
                  |                 |                |
                  |               [R10] 1 kΩ         |
                  |                 |                |
                  |                GND               |
                  |                                  |
                  +-----------[R4 1,5 MΩ]------------+   (histéresis)
                  |
                  +-------------------------------------> A0 (calibración)
```

Nodo `SENSOR` = emisor de Q2 = R3 = LM393 pin 3 = R4 = A0.
Nodo `UMBRAL` = unión de R9 y R10 = LM393 pin 2.

* Configuración de seguidor: con más luz, más corriente por Q2 y **sube** el
  voltaje en `SENSOR`. Oscuro ≈ 0 V; con el LED IR del otro Faro apuntando,
  algunos voltios.
* El LM393 compara `SENSOR` con el umbral fijo de R9/R10:
  `5 V × 1 kΩ / (10 kΩ + 1 kΩ) ≈ 0,45 V`, que en A0 se lee como ≈ 93. Salida de
  colector abierto, por eso necesita R5 (pull-up) hacia 5 V. Luz → D2 en ALTO.
* R4 (1,5 MΩ) da histéresis de ≈ `5 V × 10 kΩ / 1,5 MΩ ≈ 33 mV`, para que el
  comparador no oscile cuando la señal pasa lento por el umbral.
* **Ajustar el umbral**: el umbral debe quedar entre la lectura de A0 con el
  otro LED apagado y encendido. Si con los dos Faros a la distancia de trabajo
  `hardware/calibrar_receptor.py` no llega a LISTO, se cambia R10:

  | R10    | Umbral | En A0 | Cuándo usarla                                   |
  |--------|-------:|------:|-------------------------------------------------|
  | 470 Ω  | 0,22 V |   ≈ 46 | La señal encendida es débil (Faros lejos)      |
  | 1 kΩ   | 0,45 V |   ≈ 93 | Valor probado                                  |
  | 2,2 kΩ | 0,90 V |  ≈ 184 | Mucha luz ambiente: apagado ya pasa de ≈ 90    |

* La luz del cuarto subió la lectura "apagado" de ≈ 0 a ≈ 55. El tubo de
  termoencogible negro en Q2 (visera) es lo que más ayuda a mantener ese margen.
* A0 sólo se usa para calibrar (`faro sondear --continuo` y
  `hardware/calibrar_receptor.py`): no lo usa la recepción de tramas.
* La polaridad no importa: el firmware detecta si la señal llega invertida
  usando el SFD (ver `docs/capa1-protocolo.md`).
* R3 define sensibilidad contra velocidad: 10 kΩ es buen punto de partida
  hasta unos 4–8 kbit/s. Para buscar el puntaje extra de velocidad, probar 4,7 kΩ
  o 2,2 kΩ (más rápido, menos sensible: acercar los Faros o subir la corriente
  del LED).

### Comparador sin usar (mitad 2 del LM393)

Para que no oscile: **pin 5 (IN2+) a GND** y **pin 6 (IN2−) a +5 V**. El pin 7
(OUT2) queda al aire.

### Pines del LM393 (DIP-8, muesca a la izquierda, vista de arriba)

```
           +---U---+
   OUT1  1 |       | 8  VCC (+5V)
   IN1-  2 |       | 7  OUT2 (sin conectar)
   IN1+  3 |       | 6  IN2- -> +5V
   GND   4 |       | 5  IN2+ -> GND
           +-------+
```

## 3. Indicadores y botón de pánico

```
   D5 ---[R6 330 Ω]---|>|--- GND     LED2 verde    = TX
   D6 ---[R7 330 Ω]---|>|--- GND     LED3 amarillo = RX
   D7 ---[R8 330 Ω]---|>|--- GND     LED4 rojo     = estado / pánico

   D3 -----o  o----- GND             SW1 botón táctil (pull-up interno del Nano)
```

## 4. Alimentación y desacople

```
   +5V ---+--------+          C1 100 nF cerámico: lo más cerca posible de los
          |        |             pines 8 y 4 del LM393.
         [C1]    [C2]         C2 100 µF electrolítico (la pata con franja "−"
          |        |             va a GND): cerca de R1/Q1, absorbe el pico de
   GND ---+--------+             corriente del LED IR.
```

## Lista de conexiones (netlist) para KiCad

| Red        | Conexiones                                                      |
|------------|-----------------------------------------------------------------|
| `+5V`      | Nano 5V, R1, Q2-C, R9, R5, U1-8, U1-6, C1, C2+                   |
| `GND`      | Nano GND (ambos), Q1-E, R3, R10, U1-4, U1-5, C1, C2−, SW1, cátodos LED2–LED4 |
| `TX_BASE`  | Nano D4 — R2                                                     |
| `Q1_B`     | R2 — Q1-B                                                        |
| `LED_IR_A` | R1 — LED1 ánodo                                                  |
| `LED_IR_K` | LED1 cátodo — Q1-C                                               |
| `SENSOR`   | Q2-E, R3, U1-3, R4, Nano A0                                      |
| `UMBRAL`   | R9 — R10 — U1-2                                                  |
| `RX_OUT`   | U1-1, R5, R4, Nano D2                                            |
| `PANICO`   | Nano D3 — SW1                                                    |
| `LED_TX`   | Nano D5 — R6 — LED2 (verde)                                      |
| `LED_RX`   | Nano D6 — R7 — LED3 (amarillo)                                   |
| `LED_EST`  | Nano D7 — R8 — LED4 (rojo)                                       |

(Designadores: LED1 = LED IR; LED2–LED4 = indicadores; U1 = LM393;
Q1 = 2N2222A; Q2 = fototransistor; SW1 = botón. `D2`, `D3`… siempre se
refieren a pines del Nano.)

## Identificar patas antes de soldar

* **LED IR / LEDs**: pata larga = ánodo (+); lado plano de la cápsula = cátodo.
* **Fototransistor**: la pata del colector *no* es igual en todas las marcas.
  Revisar la hoja de datos del modelo exacto. Si no la tienen: armarlo en
  protoboard con R3 y medir el voltaje en el emisor tapándolo y apuntándole un
  control remoto de TV. Si no cambia, está al revés.
* **2N2222A en TO-92**: hay fabricantes con orden E-B-C y otros C-B-E. Con el
  multímetro en modo diodo: la base es la pata que, con la punta roja puesta
  en ella, marca ≈ 0,6–0,7 V hacia cada una de las otras dos (hacia el emisor
  marca un poco más que hacia el colector). Si el multímetro tiene zócalo hFE,
  usarlo.
* **LM393**: la muesca o punto marca el pin 1. Soldar el **zócalo**, no el
  integrado. En la **protoboard**, en cambio, el LM393 va directo: las patas
  del zócalo son muy cortas y no hacen buen contacto con los resortes.
* **Fototransistor vs. LED IR**: los dos son transparentes de 5 mm y se ven
  iguales. Antes de usarlo como emisor, mirar cada LED encendido con la cámara
  del celular (la frontal suele ver mejor el IR): si no se ve un brillo morado,
  no es un LED IR. En el kit de Diego varios "LEDs" resultaron ser sensores.
