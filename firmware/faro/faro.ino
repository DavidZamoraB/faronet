/*
 * faro.ino - Firmware del Faro (Arduino Nano / ATmega328P).
 *
 * El Faro es la interfaz de red por luz de FaroNet:
 *   - Emite tramas con un LED IR (codificacion Manchester) y las recibe
 *     con un fototransistor + comparador LM393.
 *   - Acceso al medio: CSMA con espera aleatoria exponencial y ACK con
 *     retransmision para tramas unicast.
 *   - Direccion fisica de 4 bytes en EEPROM, rotable desde el nodo.
 *   - Boton de panico: borra el secreto guardado y la direccion, limpia
 *     buffers y lo indica con los LEDs.
 *   - Habla con el nodo por USB-serial (ver enlace_serial.h).
 *
 * Pines (ver hardware/esquematico.md):
 *   D2  <- salida del comparador (INT0)
 *   D3  <- boton de panico a GND (pull-up interno)
 *   D4  -> base del transistor que maneja el LED IR (via 1 kOhm)
 *   D5  -> LED TX (verde)
 *   D6  -> LED RX (amarillo)
 *   D7  -> LED de estado / panico (rojo)
 *   A0  <- voltaje del fototransistor (solo para calibrar con SONDEAR)
 */
#include <Arduino.h>
#include <EEPROM.h>
#include "faro_core.h"
#include "enlace_serial.h"

/* ------------------------------ Pines ------------------------------ */
const uint8_t PIN_RX = 2;
const uint8_t PIN_PANICO = 3;
const uint8_t PIN_EMISOR = 4;
const uint8_t PIN_LED_TX = 5;
const uint8_t PIN_LED_RX = 6;
const uint8_t PIN_LED_ESTADO = 7;
const uint8_t PIN_SENSOR_ANALOGICO = A0;

/* Escritura/lectura rapida de pines en AVR; en otras placas se usa la
 * API normal de Arduino. */
#if defined(__AVR_ATmega328P__)
  #define EMISOR_ENCENDER() (PORTD |= _BV(PD4))
  #define EMISOR_APAGAR()   (PORTD &= ~_BV(PD4))
  #define LEER_RX()         ((uint8_t)((PIND >> PD2) & 1))
#else
  #define EMISOR_ENCENDER() digitalWrite(PIN_EMISOR, HIGH)
  #define EMISOR_APAGAR()   digitalWrite(PIN_EMISOR, LOW)
  #define LEER_RX()         ((uint8_t)digitalRead(PIN_RX))
#endif

/* ----------------------------- EEPROM ------------------------------ */
const uint8_t EE_MAGICO_0 = 0;      /* 'F'                          */
const uint8_t EE_MAGICO_1 = 1;      /* 'R'                          */
const uint8_t EE_DISENO = 2;        /* version del diseno de EEPROM */
const uint8_t EE_DIRECCION = 3;     /* 4 bytes                      */
const uint8_t EE_BPS = 7;           /* 2 bytes                      */
const uint8_t EE_OPCIONES = 9;
const uint8_t EE_REINTENTOS = 10;
const uint8_t EE_SECRETO_PRESENTE = 15;
const uint8_t EE_SECRETO = 16;      /* 32 bytes                     */
const uint8_t DISENO_EEPROM = 1;

/* ------------------------- Parametros MAC -------------------------- */
const uint16_t BPS_POR_DEFECTO = 2000;
const uint16_t BPS_MIN = 500;
const uint16_t BPS_MAX = 20000;
const uint8_t REINTENTOS_POR_DEFECTO = 3;
const uint8_t REINTENTOS_MAX = 7;
/* Tiempos en "bits" (se multiplican por la duracion de un bit). */
const uint16_t SIFS_BITS = 12;     /* espera antes de mandar un ACK     */
const uint16_t DIFS_BITS = 32;     /* canal libre antes de transmitir   */
const uint16_t RANURA_BITS = 24;   /* ranura de la espera aleatoria     */
const uint8_t VENTANA_MIN = 8;
const uint8_t VENTANA_MAX = 64;
const uint32_t ESPERA_CANAL_MAX_MS = 3000;
const uint16_t DUPLICADOS = 8;     /* (src, seq) recordados             */

/* ----------------------------- Estado ------------------------------ */
DecodificadorManchester decodificador;
volatile uint32_t ultimo_flanco_us = 0;

uint8_t mi_direccion[FARO_DIR_LEN];
uint16_t bps = BPS_POR_DEFECTO;
uint16_t bit_us = 500;
uint8_t opciones = 0;
uint8_t reintentos = REINTENTOS_POR_DEFECTO;
uint8_t secuencia = 0;

struct Estadisticas {
    uint32_t tramas_tx;
    uint32_t tramas_rx;
    uint32_t crc_malos;
    uint32_t sin_ack;
    uint32_t retransmisiones;
    uint32_t truncadas;
} estad;

/* ACK que estamos esperando mientras transmitimos */
struct {
    bool activo;
    bool recibido;
    uint8_t dir[FARO_DIR_LEN];
    uint8_t seq;
} ack_esperado;

/* Ultimas tramas aceptadas para descartar retransmisiones duplicadas */
struct Visto { uint8_t src[FARO_DIR_LEN]; uint8_t seq; bool valido; };
Visto vistos[DUPLICADOS];
uint8_t vistos_pos = 0;

/* Buffers */
uint8_t trama_tx[FARO_MAX_TRAMA];
uint8_t trama_rx[FARO_MAX_TRAMA];
uint8_t serial_entrada[FARO_MAX_TRAMA + 16];
uint8_t serial_paquete[FARO_MAX_TRAMA + 16];
uint8_t serial_salida[FARO_MAX_TRAMA + 24];
uint8_t serial_pos = 0;
bool serial_desbordado = false;

/* Panico */
volatile bool panico_pendiente = false;
uint32_t panico_desde_ms = 0;

uint32_t led_rx_hasta_ms = 0;

/* Generador pseudoaleatorio (xorshift32). Solo para esperas y para la
 * direccion de emergencia tras el panico; el nodo rota la direccion con
 * el generador criptografico del sistema operativo. */
uint32_t semilla = 0x2545F491UL;

/* ===================================================================== */
/*                           Utilidades                                   */
/* ===================================================================== */

uint32_t aleatorio() {
    semilla ^= semilla << 13;
    semilla ^= semilla >> 17;
    semilla ^= semilla << 5;
    return semilla;
}

void sembrar_aleatorio() {
    /* Ruido de pines analogicos flotantes + desfase de micros(). */
    const uint8_t pines[] = {A1, A2, A3, A6, A7};
    for (uint8_t ronda = 0; ronda < 8; ronda++) {
        for (uint8_t i = 0; i < sizeof(pines); i++) {
            semilla = (semilla << 3) ^ (semilla >> 29) ^ (uint32_t)analogRead(pines[i]) ^ micros();
        }
        if (semilla == 0) semilla = 0x2545F491UL;
        aleatorio();
    }
}

bool direccion_es_valida(const uint8_t *d) {
    bool ceros = true, unos = true;
    for (uint8_t i = 0; i < FARO_DIR_LEN; i++) {
        if (d[i] != 0x00) ceros = false;
        if (d[i] != 0xFF) unos = false;
    }
    return !ceros && !unos;
}

void generar_direccion(uint8_t *d) {
    do {
        uint32_t r = aleatorio();
        for (uint8_t i = 0; i < FARO_DIR_LEN; i++) d[i] = (uint8_t)(r >> (8 * i));
    } while (!direccion_es_valida(d));
}

void guardar_direccion() {
    for (uint8_t i = 0; i < FARO_DIR_LEN; i++) EEPROM.update(EE_DIRECCION + i, mi_direccion[i]);
}

void guardar_configuracion() {
    EEPROM.update(EE_BPS, (uint8_t)(bps >> 8));
    EEPROM.update(EE_BPS + 1, (uint8_t)(bps & 0xFF));
    EEPROM.update(EE_OPCIONES, opciones);
    EEPROM.update(EE_REINTENTOS, reintentos);
}

void fijar_bps(uint16_t nuevo) {
    bps = nuevo;
    bit_us = (uint16_t)(1000000UL / bps);
    noInterrupts();
    decodificador.configurar(bps);
    interrupts();
}

void cargar_eeprom() {
    if (EEPROM.read(EE_MAGICO_0) != 'F' || EEPROM.read(EE_MAGICO_1) != 'R' ||
        EEPROM.read(EE_DISENO) != DISENO_EEPROM) {
        /* Primer arranque: valores por defecto y direccion nueva. */
        generar_direccion(mi_direccion);
        guardar_direccion();
        bps = BPS_POR_DEFECTO;
        opciones = 0;
        reintentos = REINTENTOS_POR_DEFECTO;
        guardar_configuracion();
        for (uint8_t i = 0; i < SECRETO_LEN; i++) EEPROM.update(EE_SECRETO + i, 0);
        EEPROM.update(EE_SECRETO_PRESENTE, 0);
        EEPROM.update(EE_MAGICO_0, 'F');
        EEPROM.update(EE_MAGICO_1, 'R');
        EEPROM.update(EE_DISENO, DISENO_EEPROM);
    }
    for (uint8_t i = 0; i < FARO_DIR_LEN; i++) mi_direccion[i] = EEPROM.read(EE_DIRECCION + i);
    if (!direccion_es_valida(mi_direccion)) {
        generar_direccion(mi_direccion);
        guardar_direccion();
    }
    uint16_t guardado = ((uint16_t)EEPROM.read(EE_BPS) << 8) | EEPROM.read(EE_BPS + 1);
    if (guardado < BPS_MIN || guardado > BPS_MAX) guardado = BPS_POR_DEFECTO;
    fijar_bps(guardado);
    opciones = EEPROM.read(EE_OPCIONES) & (OPC_PROMISCUO | OPC_ENTREGAR_CRC_MALO);
    reintentos = EEPROM.read(EE_REINTENTOS);
    if (reintentos > REINTENTOS_MAX) reintentos = REINTENTOS_POR_DEFECTO;
}

/* ===================================================================== */
/*                        Enlace serial con el nodo                       */
/* ===================================================================== */

/* Termina un paquete ya armado en serial_paquete[0..n): agrega CRC,
 * lo codifica con COBS y lo manda con el delimitador 0x00. */
void finalizar_paquete(uint8_t n) {
    uint16_t c = crc16(serial_paquete, n);
    serial_paquete[n] = (uint8_t)(c >> 8);
    serial_paquete[n + 1] = (uint8_t)(c & 0xFF);
    size_t largo = cobs_codificar(serial_paquete, n + 2, serial_salida);
    serial_salida[largo++] = 0x00;
    Serial.write(serial_salida, largo);
}

void enviar_paquete(uint8_t tipo, const uint8_t *datos, uint8_t n) {
    serial_paquete[0] = tipo;
    if (n) memcpy(serial_paquete + 1, datos, n);
    finalizar_paquete(n + 1);
}

void responder_error(uint8_t codigo) {
    enviar_paquete(RSP_ERROR, &codigo, 1);
}

void escribir_u32(uint8_t *p, uint32_t v) {
    p[0] = (uint8_t)(v >> 24); p[1] = (uint8_t)(v >> 16);
    p[2] = (uint8_t)(v >> 8);  p[3] = (uint8_t)v;
}

void responder_info() {
    uint8_t r[9];
    memcpy(r, mi_direccion, FARO_DIR_LEN);
    r[4] = (uint8_t)(bps >> 8);
    r[5] = (uint8_t)(bps & 0xFF);
    r[6] = opciones;
    r[7] = reintentos;
    r[8] = EEPROM.read(EE_SECRETO_PRESENTE) == 1 ? 1 : 0;
    enviar_paquete(RSP_INFO, r, sizeof(r));
}

void responder_estadisticas() {
    uint8_t r[24];
    escribir_u32(r + 0, estad.tramas_tx);
    escribir_u32(r + 4, estad.tramas_rx);
    escribir_u32(r + 8, estad.crc_malos);
    escribir_u32(r + 12, estad.sin_ack);
    escribir_u32(r + 16, estad.retransmisiones);
    escribir_u32(r + 20, estad.truncadas);
    enviar_paquete(RSP_ESTADISTICAS, r, sizeof(r));
}

void responder_resultado_tx(uint8_t estado, uint8_t intentos, uint8_t seq) {
    uint8_t r[3] = {estado, intentos, seq};
    enviar_paquete(RSP_RESULTADO_TX, r, sizeof(r));
}

/* ===================================================================== */
/*                         Capa fisica: luz                               */
/* ===================================================================== */

void isr_flanco() {
    uint32_t ahora = micros();
    uint8_t nivel = LEER_RX();
    uint32_t dt = ahora - ultimo_flanco_us;
    ultimo_flanco_us = ahora;
    decodificador.flanco(dt > 0xFFFF ? 0xFFFF : (uint16_t)dt, nivel);
}

void receptor_activar(bool activo) {
    if (activo) {
        noInterrupts();
        decodificador.reiniciar();
        ultimo_flanco_us = micros();
        interrupts();
        attachInterrupt(digitalPinToInterrupt(PIN_RX), isr_flanco, CHANGE);
    } else {
        detachInterrupt(digitalPinToInterrupt(PIN_RX));
    }
}

/* Espera activa hasta un instante absoluto: evita que los errores de
 * temporizacion se acumulen a lo largo de la trama. */
inline void esperar_hasta(uint32_t t) {
    while ((int32_t)(micros() - t) < 0) { }
}

void emitir_byte(uint8_t b, uint32_t &t, uint16_t medio) {
    for (int8_t i = 7; i >= 0; i--) {
        bool bit = (b >> i) & 1;
        /* Manchester IEEE: 1 = apagado->encendido, 0 = encendido->apagado */
        if (bit) EMISOR_APAGAR(); else EMISOR_ENCENDER();
        t += medio;
        esperar_hasta(t);
        if (bit) EMISOR_ENCENDER(); else EMISOR_APAGAR();
        t += medio;
        esperar_hasta(t);
    }
}

/* Pone la trama en la luz: preambulo + SFD + trama. Bloqueante. */
void emitir_trama(const uint8_t *trama, uint8_t n) {
    receptor_activar(false);   /* no escucharnos a nosotros mismos */
    digitalWrite(PIN_LED_TX, HIGH);
    uint16_t medio = bit_us / 2;
    uint32_t t = micros() + 20;
    esperar_hasta(t);
    for (uint8_t i = 0; i < FARO_BYTES_PREAMBULO; i++) emitir_byte(FARO_PREAMBULO, t, medio);
    emitir_byte(FARO_SFD, t, medio);
    for (uint8_t i = 0; i < n; i++) emitir_byte(trama[i], t, medio);
    EMISOR_APAGAR();
    digitalWrite(PIN_LED_TX, LOW);
    estad.tramas_tx++;
    receptor_activar(true);
}

/* Hay portadora si el decodificador esta dentro de una trama o si ve
 * intervalos Manchester validos recientes. El ruido de la luz ambiental
 * no forma intervalos validos seguidos, asi que no bloquea el canal. */
bool canal_ocupado() {
    noInterrupts();
    uint8_t estado = decodificador.estado;
    uint8_t largos = decodificador.corrida_largos;
    uint32_t ultimo = ultimo_flanco_us;
    interrupts();
    if (estado == RX_LISTA) return false;
    if ((uint32_t)(micros() - ultimo) > 4UL * bit_us) return false;
    return estado != RX_CAZANDO || largos >= 2;
}

/* ===================================================================== */
/*                       Panico y servicio de fondo                       */
/* ===================================================================== */

void parpadear_panico() {
    for (uint8_t i = 0; i < 6; i++) {
        digitalWrite(PIN_LED_ESTADO, HIGH);
        digitalWrite(PIN_LED_TX, i & 1);
        digitalWrite(PIN_LED_RX, !(i & 1));
        delay(120);
        digitalWrite(PIN_LED_ESTADO, LOW);
        delay(80);
    }
    digitalWrite(PIN_LED_TX, LOW);
    digitalWrite(PIN_LED_RX, LOW);
    /* Queda encendido el LED rojo: el Faro esta "en blanco". */
    digitalWrite(PIN_LED_ESTADO, HIGH);
}

void ejecutar_panico() {
    panico_pendiente = false;
    EMISOR_APAGAR();

    /* 1. Borrar (zeroize) el secreto en EEPROM. Primero 0xFF y luego 0x00
     *    para no dejar el valor anterior en ninguna celda. */
    for (uint8_t i = 0; i < SECRETO_LEN; i++) EEPROM.write(EE_SECRETO + i, 0xFF);
    for (uint8_t i = 0; i < SECRETO_LEN; i++) EEPROM.write(EE_SECRETO + i, 0x00);
    EEPROM.write(EE_SECRETO_PRESENTE, 0);

    /* 2. Direccion fisica nueva para que el Faro no sea rastreable. */
    generar_direccion(mi_direccion);
    guardar_direccion();

    /* 3. Limpiar todo el estado en RAM. */
    noInterrupts();
    decodificador.reiniciar();
    memset(decodificador.buf, 0, sizeof(decodificador.buf));
    interrupts();
    memset(trama_tx, 0, sizeof(trama_tx));
    memset(trama_rx, 0, sizeof(trama_rx));
    memset(serial_entrada, 0, sizeof(serial_entrada));
    memset(serial_paquete, 0, sizeof(serial_paquete));
    memset(vistos, 0, sizeof(vistos));
    memset(&estad, 0, sizeof(estad));
    memset(&ack_esperado, 0, sizeof(ack_esperado));
    serial_pos = 0;
    secuencia = (uint8_t)aleatorio();

    /* 4. Avisar al nodo (para que borre sus llaves) y mostrarlo. */
    enviar_paquete(EVT_PANICO, mi_direccion, FARO_DIR_LEN);
    parpadear_panico();
}

/* Antirrebote: el boton debe quedar presionado 50 ms. */
void revisar_boton_panico() {
    if (digitalRead(PIN_PANICO) == LOW) {
        if (panico_desde_ms == 0) panico_desde_ms = millis() | 1;
        else if (millis() - panico_desde_ms >= 50) {
            panico_pendiente = true;
            panico_desde_ms = 0;
            while (digitalRead(PIN_PANICO) == LOW) { } /* esperar a soltar */
        }
    } else {
        panico_desde_ms = 0;
    }
}

void procesar_recepcion();

/* Lo que debe seguir funcionando mientras esperamos dentro de ENVIAR. */
void servicio() {
    revisar_boton_panico();
    procesar_recepcion();
    if (led_rx_hasta_ms && (int32_t)(millis() - led_rx_hasta_ms) >= 0) {
        digitalWrite(PIN_LED_RX, LOW);
        led_rx_hasta_ms = 0;
    }
}

void esperar_us(uint32_t us) {
    uint32_t inicio = micros();
    while ((uint32_t)(micros() - inicio) < us) {
        servicio();
        if (panico_pendiente) return;
    }
}

/* ===================================================================== */
/*                           Capa de enlace                               */
/* ===================================================================== */

bool es_duplicado(const uint8_t *src, uint8_t seq) {
    for (uint8_t i = 0; i < DUPLICADOS; i++) {
        if (vistos[i].valido && vistos[i].seq == seq &&
            memcmp(vistos[i].src, src, FARO_DIR_LEN) == 0) return true;
    }
    memcpy(vistos[vistos_pos].src, src, FARO_DIR_LEN);
    vistos[vistos_pos].seq = seq;
    vistos[vistos_pos].valido = true;
    vistos_pos = (vistos_pos + 1) % DUPLICADOS;
    return false;
}

void entregar_al_nodo(bool crc_ok, const uint8_t *trama, uint8_t n) {
    serial_paquete[0] = EVT_TRAMA_RECIBIDA;
    serial_paquete[1] = crc_ok ? 1 : 0;
    memcpy(serial_paquete + 2, trama, n);
    finalizar_paquete(n + 2);
}

void enviar_ack(const uint8_t *destino, uint8_t seq) {
    uint8_t ack[FARO_MIN_TRAMA];
    uint8_t n = trama_armar(ack, TIPO_ACK, seq, destino, mi_direccion, 0, 0);
    /* SIFS: sin escuchar el canal, el ACK tiene prioridad. */
    uint32_t t = micros() + (uint32_t)SIFS_BITS * bit_us;
    esperar_hasta(t);
    emitir_trama(ack, n);
}

void procesar_recepcion() {
    /* Trama truncada: el emisor dejo de transmitir a media trama. */
    noInterrupts();
    uint8_t estado = decodificador.estado;
    uint32_t ultimo = ultimo_flanco_us;
    if (estado != RX_CAZANDO && estado != RX_LISTA &&
        (uint32_t)(micros() - ultimo) > 3UL * bit_us) {
        decodificador.reiniciar();
        estad.truncadas++;
    }
    interrupts();
    if (estado != RX_LISTA) return;

    noInterrupts();
    uint8_t n = decodificador.longitud;
    memcpy(trama_rx, decodificador.buf, n);
    decodificador.reiniciar();
    interrupts();

    digitalWrite(PIN_LED_RX, HIGH);
    led_rx_hasta_ms = millis() + 30;

    bool crc_ok = trama_crc_valido(trama_rx, n);
    if (!crc_ok) {
        estad.crc_malos++;
        if (opciones & OPC_ENTREGAR_CRC_MALO) entregar_al_nodo(false, trama_rx, n);
        return;
    }
    estad.tramas_rx++;

    bool promiscuo = opciones & OPC_PROMISCUO;
    if (trama_rx[OFF_VER] != FARO_VERSION) {
        /* Version desconocida: solo el nodo podria entenderla. */
        if (promiscuo) entregar_al_nodo(true, trama_rx, n);
        return;
    }

    const uint8_t *dst = trama_rx + OFF_DST;
    const uint8_t *src = trama_rx + OFF_SRC;
    uint8_t tipo = trama_rx[OFF_TIPO] & TIPO_MASCARA;
    uint8_t seq = trama_rx[OFF_SEQ];
    bool para_mi = memcmp(dst, mi_direccion, FARO_DIR_LEN) == 0;
    bool difusion = memcmp(dst, FARO_DIR_DIFUSION, FARO_DIR_LEN) == 0;

    if (tipo == TIPO_ACK) {
        if (para_mi && ack_esperado.activo && seq == ack_esperado.seq &&
            memcmp(src, ack_esperado.dir, FARO_DIR_LEN) == 0) {
            ack_esperado.recibido = true;
        }
        if (promiscuo) entregar_al_nodo(true, trama_rx, n);
        return;
    }

    if (para_mi || difusion) {
        if (para_mi && (trama_rx[OFF_TIPO] & BANDERA_PIDE_ACK)) {
            enviar_ack(src, seq);
            if (es_duplicado(src, seq)) return; /* retransmision ya entregada */
        }
        entregar_al_nodo(true, trama_rx, n);
    } else if (promiscuo) {
        entregar_al_nodo(true, trama_rx, n);
    }
}

/* Duracion en microsegundos de una trama de n bytes en la luz. */
uint32_t tiempo_aire_us(uint8_t n) {
    return (uint32_t)(FARO_BYTES_PREAMBULO + 1 + n) * 8UL * bit_us;
}

/* Espera a que el canal quede libre durante DIFS. */
bool esperar_canal_libre() {
    uint32_t inicio_ms = millis();
    uint32_t libre_desde = micros();
    uint32_t difs = (uint32_t)DIFS_BITS * bit_us;
    while (true) {
        servicio();
        if (panico_pendiente) return false;
        if (canal_ocupado()) libre_desde = micros();
        else if ((uint32_t)(micros() - libre_desde) >= difs) return true;
        if (millis() - inicio_ms > ESPERA_CANAL_MAX_MS) return false;
    }
}

/*
 * MAC: CSMA/CA simplificado.
 *   1. Espera aleatoria de 0..ventana-1 ranuras (la ventana se duplica
 *      en cada reintento) y canal libre durante DIFS.
 *   2. Transmite.
 *   3. Si la trama es unicast y pide ACK, espera el ACK; si no llega,
 *      reintenta hasta `reintentos` veces.
 */
uint8_t transmitir(uint8_t n, uint8_t &intentos) {
    bool pide_ack = trama_tx[OFF_VER] == FARO_VERSION &&
                    (trama_tx[OFF_TIPO] & BANDERA_PIDE_ACK) &&
                    memcmp(trama_tx + OFF_DST, FARO_DIR_DIFUSION, FARO_DIR_LEN) != 0;
    uint8_t ventana = VENTANA_MIN;
    intentos = 0;

    for (uint8_t intento = 0; intento <= reintentos; intento++) {
        intentos = intento + 1;
        if (intento > 0) estad.retransmisiones++;

        uint32_t espera = (aleatorio() % ventana) * (uint32_t)RANURA_BITS * bit_us;
        esperar_us(espera);
        if (panico_pendiente) return TX_ABORTADO_PANICO;
        if (!esperar_canal_libre()) {
            return panico_pendiente ? TX_ABORTADO_PANICO : TX_CANAL_OCUPADO;
        }

        if (pide_ack) {
            ack_esperado.activo = true;
            ack_esperado.recibido = false;
            memcpy(ack_esperado.dir, trama_tx + OFF_DST, FARO_DIR_LEN);
            ack_esperado.seq = trama_tx[OFF_SEQ];
        }
        emitir_trama(trama_tx, n);
        if (!pide_ack) return TX_OK;

        /* Tiempo para que el otro Faro decodifique, espere SIFS y responda. */
        uint32_t limite = (uint32_t)(SIFS_BITS + 48) * bit_us + tiempo_aire_us(FARO_MIN_TRAMA);
        uint32_t inicio = micros();
        while ((uint32_t)(micros() - inicio) < limite && !ack_esperado.recibido) {
            servicio();
            if (panico_pendiente) { ack_esperado.activo = false; return TX_ABORTADO_PANICO; }
        }
        ack_esperado.activo = false;
        if (ack_esperado.recibido) return TX_OK;

        if (ventana < VENTANA_MAX) ventana *= 2;
    }
    estad.sin_ack++;
    return TX_SIN_ACK;
}

/* ===================================================================== */
/*                         Comandos del nodo                              */
/* ===================================================================== */

void cmd_enviar(const uint8_t *d, uint8_t n) {
    if (n < FARO_DIR_LEN + 1 || n - FARO_DIR_LEN - 1 > FARO_MAX_CARGA) {
        responder_resultado_tx(TX_TRAMA_INVALIDA, 0, 0);
        return;
    }
    const uint8_t *dst = d;
    uint8_t banderas = d[FARO_DIR_LEN] & BANDERA_PIDE_ACK;
    uint8_t lon = n - FARO_DIR_LEN - 1;
    uint8_t seq = secuencia++;
    uint8_t total = trama_armar(trama_tx, TIPO_DATOS | banderas, seq, dst,
                                mi_direccion, d + FARO_DIR_LEN + 1, lon);
    uint8_t intentos;
    uint8_t estado = transmitir(total, intentos);
    responder_resultado_tx(estado, intentos, seq);
}

void cmd_enviar_cruda(const uint8_t *d, uint8_t n) {
    /* La trama viene armada desde fuera del Faro (p. ej. con Scapy).
     * Solo se exige que la longitud sea coherente con el campo LON; el
     * CRC se transmite tal cual para poder probar tramas corruptas. */
    if (!trama_longitud_valida(d, n)) {
        responder_resultado_tx(TX_TRAMA_INVALIDA, 0, 0);
        return;
    }
    memcpy(trama_tx, d, n);
    uint8_t intentos;
    uint8_t estado = transmitir(n, intentos);
    responder_resultado_tx(estado, intentos, trama_tx[OFF_SEQ]);
}

void atender_comando(const uint8_t *p, uint8_t n) {
    uint8_t cmd = p[0];
    const uint8_t *d = p + 1;
    uint8_t m = n - 1;

    switch (cmd) {
    case CMD_PING: {
        uint8_t r[4] = {FW_VERSION_MAYOR, FW_VERSION_MENOR, FARO_VERSION, FARO_MAX_TRAMA};
        enviar_paquete(RSP_PONG, r, sizeof(r));
        break;
    }
    case CMD_INFO:
        responder_info();
        break;
    case CMD_ENVIAR:
        cmd_enviar(d, m);
        break;
    case CMD_ENVIAR_CRUDA:
        cmd_enviar_cruda(d, m);
        break;
    case CMD_FIJAR_DIRECCION:
        if (m != FARO_DIR_LEN || !direccion_es_valida(d)) { responder_error(ERR_PARAMETRO); break; }
        memcpy(mi_direccion, d, FARO_DIR_LEN);
        guardar_direccion();
        enviar_paquete(RSP_DIRECCION, mi_direccion, FARO_DIR_LEN);
        break;
    case CMD_ROTAR_DIRECCION:
        generar_direccion(mi_direccion);
        guardar_direccion();
        enviar_paquete(RSP_DIRECCION, mi_direccion, FARO_DIR_LEN);
        break;
    case CMD_CONFIGURAR: {
        if (m != 4) { responder_error(ERR_LONGITUD); break; }
        uint16_t nuevo = ((uint16_t)d[0] << 8) | d[1];
        if (nuevo < BPS_MIN || nuevo > BPS_MAX || d[3] > REINTENTOS_MAX) {
            responder_error(ERR_PARAMETRO);
            break;
        }
        fijar_bps(nuevo);
        opciones = d[2] & (OPC_PROMISCUO | OPC_ENTREGAR_CRC_MALO);
        reintentos = d[3];
        guardar_configuracion();
        responder_info();
        break;
    }
    case CMD_ESTADISTICAS:
        responder_estadisticas();
        break;
    case CMD_REINICIAR_ESTAD:
        memset(&estad, 0, sizeof(estad));
        responder_estadisticas();
        break;
    case CMD_GUARDAR_SECRETO:
        if (m != SECRETO_LEN) { responder_error(ERR_LONGITUD); break; }
        for (uint8_t i = 0; i < SECRETO_LEN; i++) EEPROM.update(EE_SECRETO + i, d[i]);
        EEPROM.update(EE_SECRETO_PRESENTE, 1);
        enviar_paquete(RSP_SECRETO_GUARDADO, NULL, 0);
        break;
    case CMD_LEER_SECRETO: {
        if (EEPROM.read(EE_SECRETO_PRESENTE) != 1) { responder_error(ERR_SIN_SECRETO); break; }
        uint8_t s[SECRETO_LEN];
        for (uint8_t i = 0; i < SECRETO_LEN; i++) s[i] = EEPROM.read(EE_SECRETO + i);
        enviar_paquete(RSP_SECRETO, s, SECRETO_LEN);
        memset(s, 0, sizeof(s));
        break;
    }
    case CMD_PANICO:
        panico_pendiente = true;
        break;
    case CMD_EMISOR_FIJO:
        /* Deja el LED IR encendido (o lo apaga) para medir voltajes y
         * corriente con el multimetro. Cualquier transmision lo apaga. */
        if (m != 1) { responder_error(ERR_LONGITUD); break; }
        if (d[0]) EMISOR_ENCENDER(); else EMISOR_APAGAR();
        digitalWrite(PIN_LED_TX, d[0] ? HIGH : LOW);
        delay(5);
        /* sigue: responde con la lectura del sensor */
        __attribute__((fallthrough));
    case CMD_SONDEAR: {
        uint16_t a = analogRead(PIN_SENSOR_ANALOGICO);
        uint8_t r[3] = {(uint8_t)(a >> 8), (uint8_t)(a & 0xFF), LEER_RX()};
        enviar_paquete(RSP_SONDEO, r, sizeof(r));
        break;
    }
    default:
        responder_error(ERR_COMANDO_DESCONOCIDO);
    }
}

void procesar_serial() {
    while (Serial.available()) {
        uint8_t b = Serial.read();
        if (b != 0x00) {
            if (serial_pos < sizeof(serial_entrada)) serial_entrada[serial_pos++] = b;
            else serial_desbordado = true;
            continue;
        }
        /* Fin de paquete */
        if (serial_desbordado) {
            responder_error(ERR_LONGITUD);
        } else if (serial_pos > 0) {
            size_t n = cobs_decodificar(serial_entrada, serial_pos, serial_paquete);
            if (n < 3) {
                responder_error(ERR_LONGITUD);
            } else if (crc16(serial_paquete, n) != 0) {
                /* El CRC incluido hace que el CRC del paquete completo sea 0. */
                responder_error(ERR_CRC_ENLACE);
            } else {
                /* Copiamos porque atender_comando reutiliza serial_paquete
                 * para responder. */
                uint8_t cmd[FARO_MAX_TRAMA + 8];
                memcpy(cmd, serial_paquete, n - 2);
                atender_comando(cmd, (uint8_t)(n - 2));
            }
        }
        serial_pos = 0;
        serial_desbordado = false;
        /* Un comando a la vez: ENVIAR puede tardar y el nodo espera la
         * respuesta antes de mandar el siguiente. */
        return;
    }
}

/* ===================================================================== */

void setup() {
    pinMode(PIN_EMISOR, OUTPUT);
    EMISOR_APAGAR();
    pinMode(PIN_LED_TX, OUTPUT);
    pinMode(PIN_LED_RX, OUTPUT);
    pinMode(PIN_LED_ESTADO, OUTPUT);
    pinMode(PIN_RX, INPUT);
    pinMode(PIN_PANICO, INPUT_PULLUP);

    Serial.begin(ENLACE_BAUDIOS);
    sembrar_aleatorio();
    cargar_eeprom();
    secuencia = (uint8_t)aleatorio();

    /* Saludo visual: los tres LEDs encienden en secuencia. */
    const uint8_t leds[] = {PIN_LED_TX, PIN_LED_RX, PIN_LED_ESTADO};
    for (uint8_t i = 0; i < 3; i++) {
        digitalWrite(leds[i], HIGH);
        delay(120);
        digitalWrite(leds[i], LOW);
    }
    receptor_activar(true);
}

void loop() {
    servicio();
    if (panico_pendiente) ejecutar_panico();
    procesar_serial();
    if (panico_pendiente) ejecutar_panico();
}
