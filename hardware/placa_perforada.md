# Montaje en placa perforada

Guía para pasar el circuito de [esquematico.md](esquematico.md) de la
protoboard a una placa perforada de 5 × 7 cm (≈ 18 × 24 agujeros, paso
2,54 mm). **Primero hay que tenerlo funcionando en protoboard** con el firmware
(`faro info`, `faro sondear`, una trama de ida y vuelta). Solo después se suelda.

## Distribución (vista superior, lado de componentes)

```
        col 1                                                      col 24
        +-----------------------------------------------------------+
  fila1 | ====================== riel +5V (alambre desnudo) ======== |
        |                                                           |
        |  [=== header hembra 1x15: A0 ... 5V ... VIN ===]   C1     |
        |                                                  +-----+  |  LED1 (IR) ->
 USB ===|           ARDUINO NANO                           | U1  |  |
 (nodo) |        (va montado sobre los headers)            |LM393|  |  ~2 cm de
        |                                                  +-----+  |  separación
        |  [=== header hembra 1x15: D12 ... D2 ... TX1 ==] R9 R10   |
        |                                                           |  Q2 + tubo ->
        |   R2  Q1  R1  C2                         R3  R4  R5       |
        |                                                           |
        |   R6  R7  R8                                              |
        |   LED2 LED3 LED4            SW1                           |
 fila18 | ====================== riel GND ========================== |
        +-----------------------------------------------------------+
```

Ideas detrás de la distribución:

* **USB hacia afuera** por un borde, para conectar el cable sin forzar nada.
* **Óptica en el borde opuesto**: LED1 y Q2 asoman por el canto de la placa,
  doblando las patas 90°, de modo que el Faro "mira" hacia el otro Faro.
  Separarlos al menos 2 cm, o poner entre ellos un trozo de cartón negro, para
  que el LED propio no encandile al fototransistor propio.
* **Tubo óptico**: 2–3 cm de termoencogible negro alrededor de Q2 (sin
  calentarlo del todo, que quede como visera). Corta luz del techo y de las
  ventanas y es lo que más mejora el BER.
* **Rieles de +5V y GND** a lo largo de los bordes superior e inferior, con
  alambre desnudo (o la pata sobrante de una resistencia) soldado agujero por
  agujero. Todo lo que necesita 5 V o GND llega al riel por el camino más corto.
* **LM393 cerca de Q2**: el cable `SENSOR` es el más sensible al ruido, que sea
  corto.
* **C1 pegado al LM393** (pines 8 y 4) y **C2 pegado a R1/Q1**.
* **LEDs y botón en el borde inferior**, visibles y fáciles de presionar
  durante la defensa.

> Antes de soldar nada, coloquen todas las piezas sobre la placa sin soldar y
> tomen una foto: así comprueban que todo cabe y tienen la referencia.

## Orden de soldadura

De lo más bajo a lo más alto. Así la placa queda apoyada y plana al soltarla.

1. **Rieles** de +5V y GND (alambre desnudo).
2. **Puentes** (cables cortos sobre la placa) y resistencias acostadas:
   R1–R10. Doblar las patas con la distancia justa, sin tensión.
3. **Zócalo DIP-8** de U1 (sin el LM393 puesto). Muesca hacia el mismo lado
   que en el esquemático.
4. **Headers hembra** del Nano. Truco: poner el Nano encajado en los headers
   mientras se sueldan, para que queden paralelos y a la distancia exacta.
   Retirar el Nano después de soldar las dos puntas de cada tira y antes de
   seguir con el resto (el calor no le hace bien).
5. C1 y botón SW1.
6. Q1 (2N2222A): verificar el orden E-B-C con el multímetro **antes**.
7. C2 (electrolítico): la franja "−" va a GND.
8. LEDs indicadores (pata larga = ánodo hacia la resistencia).
9. LED1 y Q2 en el borde, con las patas dobladas.
10. Cableado: el cable del lado de abajo, corto y pegado a la placa. Usar
    colores consistentes: rojo = +5V, negro = GND, otro color = señales.

## Técnica de soldadura

* Cautín a ≈ 330–350 °C para estaño con plomo, 370 °C para estaño sin plomo.
  Punta limpia y estañada (pasarla por la esponja húmeda o la viruta de bronce).
* **Calentar la unión, no el estaño**: apoyar la punta tocando a la vez la pata
  y el cobre del agujero 1–2 s, luego acercar el estaño al otro lado de la
  pata. Se funde con el calor de la unión y corre solo.
* Retirar primero el estaño y después la punta. No mover la pieza hasta que
  solidifique (2–3 s).
* Cortar las patas sobrantes a ras del cono con el cortafríos.

### Criterios de calidad (los que revisa el profesor)

| Bien ✔                                           | Mal ✘                                       |
|--------------------------------------------------|---------------------------------------------|
| Cono cóncavo, brillante, cubre el anillo de cobre | Bola redonda encima (no mojó el cobre)      |
| Se ve el contorno de la pata dentro del estaño    | Gris y granulado: **junta fría**, rehacer   |
| Cada junta separada de la vecina                  | Puente de estaño entre dos agujeros         |
| Cables cortos, rectos, pegados a la placa         | Cables largos en arco, cruzados             |

Para corregir: malla desoldante sobre la junta + punta del cautín encima; la
malla absorbe el estaño.

## Fotografías (entregable)

Tomar con buena luz, la placa ocupando casi todo el cuadro y enfocada:

* `fotos/superior.jpg`: lado de componentes, con el Nano puesto.
* `fotos/inferior.jpg`: lado de las soldaduras.
* `fotos/funcionando.jpg` (opcional): los dos Faros enfrentados con los LEDs
  TX/RX encendidos.

Las fotos van en `hardware/fotos/` con ese nombre.
