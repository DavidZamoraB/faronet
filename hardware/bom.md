# Lista de materiales (BOM)

Precios **aproximados** en colones (tiendas de electrónica en Costa Rica,
octubre 2026). Antes de entregar, reemplazarlos por los de la factura real y
anotar la tienda.

FaroNet necesita **dos Faros** (uno por comunidad), así que se compra todo ×2.
Conviene comprar repuestos de lo que se quema o se pierde fácil (LED IR,
fototransistor, LM393).

## Por Faro

| #  | Designador | Componente                                         | Cant. | ₡ unidad | ₡ total |
|----|------------|----------------------------------------------------|------:|---------:|--------:|
| 1  | —          | Arduino Nano V3 (clon con CH340) o Arduino Uno      | 1 | 5 500 | 5 500 |
| 2  | —          | Header hembra 1×40, 2,54 mm (cortar 2 × 15)         | 1 |   600 |   600 |
| 3  | —          | Placa perforada 5 × 7 cm (FR4, doble cara)          | 1 |   900 |   900 |
| 4  | LED1       | LED infrarrojo 940 nm, 5 mm                         | 1 |   200 |   200 |
| 5  | Q2         | Fototransistor IR 5 mm con filtro (PT333-3C o similar) | 1 |   350 |   350 |
| 6  | U1         | Comparador LM393, DIP-8                             | 1 |   400 |   400 |
| 7  | —          | Zócalo DIP-8                                        | 1 |   150 |   150 |
| 8  | Q1         | Transistor NPN 2N2222A (TO-92)                      | 1 |   150 |   150 |
| 9  | R1         | Resistencia 82 Ω 1/4 W                              | 1 |    30 |    30 |
| 10 | R2         | Resistencia 1 kΩ 1/4 W                              | 1 |    30 |    30 |
| 11 | R3         | Resistencia 10 kΩ 1/4 W                             | 1 |    30 |    30 |
| 12 | R4         | Resistencia 1,5 MΩ 1/4 W                            | 1 |    30 |    30 |
| 13 | R5         | Resistencia 10 kΩ 1/4 W                             | 1 |    30 |    30 |
| 14 | R9         | Resistencia 10 kΩ 1/4 W (umbral, lado +5V)          | 1 |    30 |    30 |
| 15 | R10        | Resistencia 1 kΩ 1/4 W (umbral, lado GND)           | 1 |    30 |    30 |
| 16 | R6–R8      | Resistencia 330 Ω 1/4 W                             | 3 |    30 |    90 |
| 17 | LED2       | LED verde 5 mm (TX)                                 | 1 |    75 |    75 |
| 18 | LED3       | LED amarillo 5 mm (RX)                              | 1 |    75 |    75 |
| 19 | LED4       | LED rojo 5 mm (estado / pánico)                     | 1 |    75 |    75 |
| 20 | SW1        | Botón táctil 6 × 6 mm                               | 1 |   100 |   100 |
| 21 | C1         | Capacitor cerámico 100 nF                           | 1 |    50 |    50 |
| 22 | C2         | Capacitor electrolítico 100 µF 16 V                 | 1 |   100 |   100 |
| 23 | —          | Termoencogible negro 5–6 mm, 3 cm (tubo óptico)     | 1 |   150 |   150 |
| 24 | —          | Cable USB para el Nano (mini-B o según modelo)      | 1 | 1 500 | 1 500 |
|    |            | **Subtotal por Faro**                               |   |       | **10 675** |

## Compartido (una vez por grupo)

| Componente                                  | Cant. | ₡ total |
|---------------------------------------------|------:|--------:|
| Cable sólido 22 AWG (3 colores: rojo, negro, otro) | 1 | 1 200 |
| Estaño 60/40 o 63/37 con resina, 0,8 mm     | 1 | 2 000 |
| Malla desoldante                            | 1 |   800 |
| Repuestos: 2 LED IR, 2 fototransistores, 1 LM393 | — | 1 500 |
| Resistencias de 470 Ω y 2,2 kΩ (para ajustar R10, ver esquemático) | 2 | 60 |
| **Subtotal compartido**                     |   | **5 560** |

## Total

| Concepto                    | ₡       |
|-----------------------------|--------:|
| 2 Faros × 10 675            | 21 350  |
| Compartido                  |  5 560  |
| **Total del proyecto (hardware)** | **26 910** |

No se incluyen herramientas (cautín, multímetro, pinzas) porque se reutilizan.

## Cambios respecto al diseño original

Los valores de R4, R5 y el umbral son los del Faro de Diego, probado en
protoboard (ver la nota al inicio de [esquematico.md](esquematico.md)):

| Designador | Antes          | Ahora                      | Por qué |
|------------|----------------|----------------------------|---------|
| RV1        | Trimpot 10 kΩ  | Se quita                   | El trimpot del kit no variaba el voltaje |
| R9, R10    | —              | 10 kΩ y 1 kΩ (divisor fijo) | Umbral estable de ≈ 0,45 V sin ajuste |
| R4         | 1 MΩ           | 1,5 MΩ                     | No había de 1 MΩ; funciona igual (menos histéresis) |
| R5         | 4,7 kΩ         | 10 kΩ                      | No había de 4,7 kΩ; sirve como pull-up |

## Notas de compra

* **Fototransistor con filtro de luz diurna** (cápsula negra o azul oscuro):
  rechaza buena parte de la luz visible del aula y mejora mucho el BER. Debe ser
  para 940 nm, igual que el LED IR.
* Si la tienda solo tiene el sensor "TCRT5000" o un módulo "sensor IR" ya armado
  con LM393: sirven para prototipar, pero el enunciado pide soldar la etapa de
  acondicionamiento nosotros mismos.
* Si el Nano trae los pines ya soldados (machos), igual se usan los headers
  hembra en la placa para poder retirarlo (requisito del enunciado).
* **No sirve el módulo receptor de control remoto** (3 patas con domo negro,
  tipo VS1838): solo detecta luz que parpadea a 38 kHz y deforma la señal
  Manchester. El receptor es el fototransistor de 2 patas.
* **Arduino Pro Mini**: solo si es de 5 V / 16 MHz, y hay que sumar un
  adaptador USB-serial (≈ ₡2 500–3 500) y soldarle los headers.
* El clon con CH340 puede necesitar driver en Windows. En Linux funciona directo
  (`/dev/ttyUSB0`).
