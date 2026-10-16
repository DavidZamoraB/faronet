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
| 1  | —          | Arduino Nano V3 (clon con CH340)                    | 1 | 5 500 | 5 500 |
| 2  | —          | Header hembra 1×40, 2,54 mm (cortar 2 × 15)         | 1 |   600 |   600 |
| 3  | —          | Placa perforada 5 × 7 cm (FR4, doble cara)          | 1 |   900 |   900 |
| 4  | LED1       | LED infrarrojo 940 nm, 5 mm                         | 1 |   200 |   200 |
| 5  | Q2         | Fototransistor IR 5 mm con filtro (PT333-3C o similar) | 1 |   350 |   350 |
| 6  | U1         | Comparador LM393, DIP-8                             | 1 |   400 |   400 |
| 7  | —          | Zócalo DIP-8                                        | 1 |   150 |   150 |
| 8  | Q1         | Transistor NPN 2N2222A (TO-92)                      | 1 |   150 |   150 |
| 9  | RV1        | Trimpot 10 kΩ (vertical)                            | 1 |   300 |   300 |
| 10 | R1         | Resistencia 82 Ω 1/4 W                              | 1 |    30 |    30 |
| 11 | R2         | Resistencia 1 kΩ 1/4 W                              | 1 |    30 |    30 |
| 12 | R3         | Resistencia 10 kΩ 1/4 W                             | 1 |    30 |    30 |
| 13 | R4         | Resistencia 1 MΩ 1/4 W                              | 1 |    30 |    30 |
| 14 | R5         | Resistencia 4,7 kΩ 1/4 W                            | 1 |    30 |    30 |
| 15 | R6–R8      | Resistencia 330 Ω 1/4 W                             | 3 |    30 |    90 |
| 16 | LED2       | LED verde 5 mm (TX)                                 | 1 |    75 |    75 |
| 17 | LED3       | LED amarillo 5 mm (RX)                              | 1 |    75 |    75 |
| 18 | LED4       | LED rojo 5 mm (estado / pánico)                     | 1 |    75 |    75 |
| 19 | SW1        | Botón táctil 6 × 6 mm                               | 1 |   100 |   100 |
| 20 | C1         | Capacitor cerámico 100 nF                           | 1 |    50 |    50 |
| 21 | C2         | Capacitor electrolítico 100 µF 16 V                 | 1 |   100 |   100 |
| 22 | —          | Termoencogible negro 5–6 mm, 3 cm (tubo óptico)     | 1 |   150 |   150 |
| 23 | —          | Cable USB para el Nano (mini-B o según modelo)      | 1 | 1 500 | 1 500 |
|    |            | **Subtotal por Faro**                               |   |       | **10 915** |

## Compartido (una vez por grupo)

| Componente                                  | Cant. | ₡ total |
|---------------------------------------------|------:|--------:|
| Cable sólido 22 AWG (3 colores: rojo, negro, otro) | 1 | 1 200 |
| Estaño 60/40 o 63/37 con resina, 0,8 mm     | 1 | 2 000 |
| Malla desoldante                            | 1 |   800 |
| Repuestos: 2 LED IR, 2 fototransistores, 1 LM393 | — | 1 500 |
| **Subtotal compartido**                     |   | **5 500** |

## Total

| Concepto                    | ₡       |
|-----------------------------|--------:|
| 2 Faros × 10 915            | 21 830  |
| Compartido                  |  5 500  |
| **Total del proyecto (hardware)** | **27 330** |

No se incluyen herramientas (cautín, multímetro, pinzas) porque se reutilizan.

## Notas de compra

* **Fototransistor con filtro de luz diurna** (cápsula negra o azul oscuro):
  rechaza buena parte de la luz visible del aula y mejora mucho el BER. Debe ser
  para 940 nm, igual que el LED IR.
* Si la tienda solo tiene el sensor "TCRT5000" o un módulo "sensor IR" ya armado
  con LM393: sirven para prototipar, pero el enunciado pide soldar la etapa de
  acondicionamiento nosotros mismos.
* Si el Nano trae los pines ya soldados (machos), igual se usan los headers
  hembra en la placa para poder retirarlo (requisito del enunciado).
* El clon con CH340 puede necesitar driver en Windows. En Linux funciona directo
  (`/dev/ttyUSB0`).
