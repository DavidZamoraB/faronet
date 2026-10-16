/*
 * faro_core.cpp - Implementacion de la logica de Capa 1 (ver faro_core.h).
 */
#include "faro_core.h"
#include <string.h>

const uint8_t FARO_DIR_DIFUSION[FARO_DIR_LEN] = {0xFF, 0xFF, 0xFF, 0xFF};

/* ----------------------------- CRC-16 ----------------------------- */

uint16_t crc16_continuar(uint16_t crc, const uint8_t *datos, size_t n) {
    while (n--) {
        crc ^= (uint16_t)(*datos++) << 8;
        for (uint8_t i = 0; i < 8; i++) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021) : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

uint16_t crc16(const uint8_t *datos, size_t n) {
    return crc16_continuar(0xFFFF, datos, n);
}

/* ----------------------------- Tramas ----------------------------- */

uint8_t trama_armar(uint8_t *salida, uint8_t tipo, uint8_t seq,
                    const uint8_t *dst, const uint8_t *src,
                    const uint8_t *carga, uint8_t lon) {
    if (lon > FARO_MAX_CARGA) return 0;
    salida[OFF_VER] = FARO_VERSION;
    salida[OFF_LON] = lon;
    salida[OFF_TIPO] = tipo;
    salida[OFF_SEQ] = seq;
    memcpy(salida + OFF_DST, dst, FARO_DIR_LEN);
    memcpy(salida + OFF_SRC, src, FARO_DIR_LEN);
    if (lon) memcpy(salida + OFF_CARGA, carga, lon);
    uint16_t c = crc16(salida, FARO_CABECERA + lon);
    salida[FARO_CABECERA + lon] = (uint8_t)(c >> 8);
    salida[FARO_CABECERA + lon + 1] = (uint8_t)(c & 0xFF);
    return (uint8_t)trama_longitud_total(lon);
}

bool trama_longitud_valida(const uint8_t *trama, uint8_t n) {
    if (n < FARO_MIN_TRAMA || n > FARO_MAX_TRAMA) return false;
    return trama_longitud_total(trama[OFF_LON]) == n;
}

bool trama_crc_valido(const uint8_t *trama, uint8_t n) {
    if (!trama_longitud_valida(trama, n)) return false;
    uint16_t c = crc16(trama, n - FARO_CRC);
    return trama[n - 2] == (uint8_t)(c >> 8) && trama[n - 1] == (uint8_t)(c & 0xFF);
}

/* ------------------------------ COBS ------------------------------ */

size_t cobs_codificar(const uint8_t *entrada, size_t n, uint8_t *salida) {
    size_t lectura = 0, escritura = 1, pos_codigo = 0;
    uint8_t codigo = 1;
    while (lectura < n) {
        if (entrada[lectura] == 0) {
            salida[pos_codigo] = codigo;
            pos_codigo = escritura++;
            codigo = 1;
        } else {
            salida[escritura++] = entrada[lectura];
            if (++codigo == 0xFF) {
                salida[pos_codigo] = codigo;
                pos_codigo = escritura++;
                codigo = 1;
            }
        }
        lectura++;
    }
    salida[pos_codigo] = codigo;
    return escritura;
}

size_t cobs_decodificar(const uint8_t *entrada, size_t n, uint8_t *salida) {
    size_t lectura = 0, escritura = 0;
    while (lectura < n) {
        uint8_t codigo = entrada[lectura];
        if (codigo == 0 || lectura + codigo > n) return 0;
        lectura++;
        for (uint8_t i = 1; i < codigo; i++) {
            if (entrada[lectura] == 0) return 0;
            salida[escritura++] = entrada[lectura++];
        }
        if (codigo != 0xFF && lectura != n) salida[escritura++] = 0;
    }
    return escritura;
}

/* ---------------------- Decodificador Manchester ------------------- */

/* Intervalos entre flancos: CORTO ~ medio bit, LARGO ~ bit completo.  */
enum { INTERVALO_INVALIDO, INTERVALO_CORTO, INTERVALO_LARGO };

/* Intervalos largos seguidos que hacen falta para fijar la alineacion. */
#define LARGOS_PARA_SINCRONIZAR 8
/* Bits maximos tras sincronizar sin ver el SFD antes de rendirse.     */
#define MAX_BITS_SIN_SFD 64

void DecodificadorManchester::configurar(uint16_t bits_por_segundo) {
    medio_bit_us = (uint16_t)(500000UL / bits_por_segundo);
    reiniciar();
}

void DecodificadorManchester::reiniciar() {
    estado = RX_CAZANDO;
    corrida_largos = 0;
    esperando_corto = 0;
    invertido = 0;
    bits_sin_sfd = 0;
    registro = 0;
    byte_actual = 0;
    bits_en_byte = 0;
    esperados = 0;
    longitud = 0;
}

void DecodificadorManchester::flanco(uint16_t dt_us, uint8_t nivel) {
    if (estado == RX_LISTA) return; /* el lazo principal aun no la leyo */

    /* Tolerancia de +-50% de medio bit sobre cada tipo de intervalo. */
    uint16_t h = medio_bit_us;
    uint8_t clase;
    if (dt_us >= h / 2 && dt_us < h + h / 2) clase = INTERVALO_CORTO;
    else if (dt_us >= h + h / 2 && dt_us < 2 * h + h / 2) clase = INTERVALO_LARGO;
    else clase = INTERVALO_INVALIDO;

    if (clase == INTERVALO_INVALIDO) {
        if (estado != RX_CAZANDO) reiniciar();
        corrida_largos = 0;
        return;
    }

    if (estado == RX_CAZANDO) {
        /* El preambulo 0x55 solo produce intervalos largos y en ese caso
         * cada flanco cae a mitad de bit: tras varios seguidos ya sabemos
         * donde estamos parados. */
        if (clase == INTERVALO_LARGO) {
            if (++corrida_largos >= LARGOS_PARA_SINCRONIZAR) {
                estado = RX_SINCRONIZADO;
                registro = 0;
                bits_sin_sfd = 0;
                esperando_corto = 0;
                bit_recibido(nivel);
            }
        } else {
            corrida_largos = 0;
        }
        return;
    }

    /* Ya alineados: el flanco anterior fue de mitad de bit (o de frontera
     * si esperando_corto). Largo = siguiente mitad de bit. Corto = flanco
     * de frontera, que debe ir seguido de otro corto. */
    if (clase == INTERVALO_LARGO) {
        if (esperando_corto) { reiniciar(); return; }
        bit_recibido(nivel);
    } else if (!esperando_corto) {
        esperando_corto = 1;
    } else {
        esperando_corto = 0;
        bit_recibido(nivel);
    }
}

void DecodificadorManchester::bit_recibido(uint8_t nivel) {
    if (estado == RX_SINCRONIZADO) {
        registro = (uint16_t)((registro << 1) | (nivel & 1));
        /* Probamos ambas polaridades: si el comparador invierte la senal
         * el patron llega negado y lo corregimos aqui. */
        if (registro == FARO_PATRON_SYNC) {
            invertido = 0;
        } else if (registro == (uint16_t)~FARO_PATRON_SYNC) {
            invertido = 1;
        } else {
            if (++bits_sin_sfd > MAX_BITS_SIN_SFD) reiniciar();
            return;
        }
        estado = RX_RECIBIENDO;
        byte_actual = 0;
        bits_en_byte = 0;
        longitud = 0;
        esperados = 0;
        return;
    }

    /* RX_RECIBIENDO: bytes MSB primero */
    byte_actual = (uint8_t)((byte_actual << 1) | ((nivel ^ invertido) & 1));
    if (++bits_en_byte < 8) return;

    buf[longitud++] = byte_actual;
    byte_actual = 0;
    bits_en_byte = 0;

    if (longitud == OFF_LON + 1) {
        uint16_t total = trama_longitud_total(buf[OFF_LON]);
        if (total > FARO_MAX_TRAMA) { reiniciar(); return; }
        esperados = (uint8_t)total;
    }
    if (esperados && longitud >= esperados) {
        estado = RX_LISTA;
    }
}
