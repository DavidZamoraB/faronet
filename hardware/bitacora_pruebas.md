# Bitácora de pruebas con multímetro

Llenar una copia por Faro (`Faro A` y `Faro B`). Anotar fecha, quién midió y el
valor **realmente medido**. La columna "Esperado" es la guía para saber si algo
está mal.

Faro: ______  Fecha: __________  Midió: ______________

## 1. Antes de energizar (sin USB, Nano y LM393 retirados)

Multímetro en modo continuidad (pitido) o en Ω.

| # | Prueba                                         | Esperado             | Medido | ✔/✘ |
|---|------------------------------------------------|----------------------|--------|-----|
| 1 | Riel +5V ↔ riel GND (en Ω)                     | **≈ 10 kΩ** (es el trimpot RV1); nunca ≈ 0 Ω | | |
| 2 | Riel +5V ↔ pin 5V del header del Nano          | Continuidad          |        |     |
| 3 | Riel GND ↔ los dos pines GND del header        | Continuidad          |        |     |
| 4 | Zócalo pin 8 ↔ +5V; pin 4 ↔ GND                | Continuidad          |        |     |
| 5 | Zócalo pin 5 ↔ GND; pin 6 ↔ +5V                | Continuidad          |        |     |
| 6 | Zócalo pin 3 ↔ header A0 ↔ emisor de Q2        | Continuidad          |        |     |
| 7 | Zócalo pin 1 ↔ header D2                       | Continuidad          |        |     |
| 8 | Zócalo pin 2 ↔ cursor de RV1                   | Continuidad          |        |     |
| 9 | Header D4 ↔ base de Q1 (en Ω)                  | ≈ 1 kΩ (R2)          |        |     |
| 10| Emisor de Q1 ↔ GND                             | Continuidad          |        |     |
| 11| Header D3 ↔ GND con SW1 presionado / suelto    | Continuidad / abierto |       |     |
| 12| Pines vecinos del header (D2↔D3, D3↔D4…)       | Sin continuidad      |        |     |
| 13| Pines vecinos del zócalo (1↔2, 2↔3…)           | Sin continuidad      |        |     |
| 14| R1, R3, R5 medidas en la placa (Ω)             | ≈ 82 / 10 k / 4,7 k  |        |     |

> La prueba 1 es la más importante: **si hay corto entre +5V y GND no se
> conecta el USB** hasta encontrarlo. Sin pitido en continuidad y ≈ 10 kΩ en
> ohmios es lo correcto. Con C2 montado, el multímetro en Ω puede
> marcar un valor que sube poco a poco (el capacitor se carga): eso es normal;
> un valor fijo cercano a 0 Ω no lo es.

## 2. Con energía (Nano y LM393 puestos, USB conectado)

Punta negra en GND. Para las mediciones del emisor usar
`faro -p /dev/ttyUSB0 emisor encender` y luego `emisor apagar`.

| #  | Punto de medición                               | Condición          | Esperado        | Medido | ✔/✘ |
|----|-------------------------------------------------|--------------------|-----------------|--------|-----|
| 15 | Riel +5V                                        | reposo             | 4,6 – 5,1 V     |        |     |
| 16 | LM393 pin 8                                     | reposo             | igual que +5V   |        |     |
| 17 | LM393 pin 2 (umbral)                            | girar RV1          | 0 – 5 V, varía  |        |     |
| 18 | Nodo SENSOR (A0)                                | Q2 tapado          | < 0,3 V         |        |     |
| 19 | Nodo SENSOR (A0)                                | luz del aula       | ______ V        |        |     |
| 20 | Nodo SENSOR (A0)                                | LED IR del otro Faro encendido a 10 cm | claramente mayor que #19 | | |
| 21 | D2 (salida comparador)                          | Q2 tapado          | ≈ 0 V           |        |     |
| 22 | D2 (salida comparador)                          | LED IR del otro Faro encendido | ≈ 5 V |        |     |
| 23 | Base de Q1                                      | emisor apagado     | 0 V             |        |     |
| 24 | Base de Q1                                      | emisor encendido   | 0,7 – 0,9 V     |        |     |
| 25 | Colector de Q1 (Vce)                            | emisor encendido   | < 0,3 V (saturado) |     |     |
| 26 | Voltaje sobre R1                                | emisor encendido   | ≈ 3,2 – 3,7 V   |        |     |
| 27 | Corriente del LED IR = V(R1) / 82 Ω             | emisor encendido   | 39 – 45 mA      |        |     |
| 28 | Voltaje sobre LED IR (ánodo − cátodo)           | emisor encendido   | 1,1 – 1,4 V     |        |     |

## 3. Calibración del umbral

1. Enfrentar los dos Faros a la distancia de trabajo.
2. En el Faro receptor: `faro -p /dev/ttyUSB0 sondear --continuo` y anotar la
   lectura analógica (0–1023) con el LED del otro **apagado** (`L_off`) y
   **encendido** (`L_on`, usando `faro -p <otro puerto> emisor encender`).
3. Ajustar RV1 hasta que el voltaje en LM393 pin 2 quede a la mitad:
   `V_umbral ≈ (L_off + L_on) / 2 × 5 V / 1023`.
4. Verificar que `comparador=` cambie de 0 a 1 al encender el otro LED.

| Distancia | L_off | L_on | V_umbral ajustado |
|-----------|-------|------|-------------------|
|           |       |      |                   |

## 4. Tasa de transferencia efectiva y BER (≥ 3 distancias, luz ambiente normal)

En el Faro **receptor**:

```bash
faro -p /dev/ttyUSB0 medir receptor --tramas 200 --tam 114 --distancia 50cm --csv ../hardware/mediciones.csv
```

En el Faro **emisor** (otra terminal / otra PC):

```bash
faro -p /dev/ttyUSB1 medir emisor --tramas 200 --tam 114
```

Repetir para cada distancia y cada velocidad (`faro configurar --bps N` en
**los dos** Faros). El CSV acumula todas las corridas.

| Distancia | bps línea | Tramas recibidas | CRC ok | BER | Tasa efectiva (bit/s) | Luz ambiente |
|-----------|-----------|------------------|--------|-----|-----------------------|--------------|
| 10 cm     |           |                  |        |     |                       |              |
| 50 cm     |           |                  |        |     |                       |              |
| 1 m       |           |                  |        |     |                       |              |
| 1,5 m     |           |                  |        |     |                       |              |

## Observaciones / problemas encontrados

-
