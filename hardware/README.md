# hardware

El Faro: Arduino Nano (o Uno) + emisor IR con transistor + receptor con fototransistor y
comparador LM393 + LEDs TX/RX/estado + botón de pánico, soldado en placa
perforada con headers para poder retirar el Nano.

| Archivo | Contenido |
| --- | --- |
| [esquematico.md](esquematico.md) | Circuito por bloques, cálculos, netlist para KiCad y cómo identificar patas |
| [bom.md](bom.md) | Lista de materiales con costo aproximado en colones |
| [placa_perforada.md](placa_perforada.md) | Distribución en la placa, orden de soldadura, técnica y criterios de calidad |
| [bitacora_pruebas.md](bitacora_pruebas.md) | Plantilla de pruebas con multímetro, calibración y medición de BER |
| [calibrar_receptor.py](calibrar_receptor.py) | Prueba del umbral del receptor: alterna el LED IR propio y muestra A0 y el comparador |
| `fotos/` | Fotos de ambas caras de la placa (pendiente) |
| `kicad/` | Proyecto KiCad del esquemático (pendiente) |

## Flujo recomendado

1. Comprar materiales ([bom.md](bom.md)), con repuestos.
2. Armar en **protoboard** siguiendo [esquematico.md](esquematico.md).
3. Cargar el firmware ([../firmware/README.md](../firmware/README.md)) y probar:
   `faro info`, `faro sondear --continuo`, `python hardware/calibrar_receptor.py`, mandar tramas entre
   los dos Faros.
4. Dibujar el esquemático en KiCad a partir del prototipo que funciona.
5. Pruebas de continuidad y soldadura en placa ([placa_perforada.md](placa_perforada.md)),
   llenando [bitacora_pruebas.md](bitacora_pruebas.md) en el camino.
6. Medir tasa efectiva y BER a 3+ distancias.
