/*
 * faro_core.h - Logica de Capa 1 del Faro independiente del hardware.
 *
 * Todo lo que esta aqui compila tanto en Arduino como en una PC (g++),
 * de modo que se puede probar sin el Faro fisico (ver test/test_core.cpp).
 *
 * Contenido:
 *   - Formato de la trama FaroNet Capa 1 (version 1).
 *   - CRC-16/CCITT-FALSE (integridad de la trama y del enlace serial).
 *   - COBS (delimitacion de paquetes en el enlace USB-serial con el nodo).
 *   - Decodificador Manchester alimentado por flancos (tiempo + nivel).
 */
#ifndef FARO_CORE_H
#define FARO_CORE_H

#include <stdint.h>
#include <stddef.h>

/* ------------------------------------------------------------------ */
/* Trama Capa 1 (version 1)                                            */
/*                                                                     */
/*  0      1      2      3      4..7   8..11  12..12+LON-1   +2        */
/* +------+------+------+------+------+------+------------+-------+    */
/* | VER  | LON  | TIPO | SEQ  | DST  | SRC  |  CARGA     | CRC16 |    */
/* +------+------+------+------+------+------+------------+-------+    */
/*                                                                     */
/* VER y LON SIEMPRE ocupan los bytes 0 y 1 en cualquier version, y la */
/* trama completa mide FARO_CABECERA + LON + FARO_CRC. Asi el receptor */
/* puede delimitar tramas de versiones futuras sin entenderlas.        */
/* ------------------------------------------------------------------ */
#define FARO_VERSION        0x01
#define FARO_DIR_LEN        4
#define FARO_CABECERA       12
#define FARO_CRC            2
#define FARO_MAX_TRAMA      128
#define FARO_MAX_CARGA      (FARO_MAX_TRAMA - FARO_CABECERA - FARO_CRC) /* 114 */
#define FARO_MIN_TRAMA      (FARO_CABECERA + FARO_CRC)

#define OFF_VER     0
#define OFF_LON     1
#define OFF_TIPO    2
#define OFF_SEQ     3
#define OFF_DST     4
#define OFF_SRC     8
#define OFF_CARGA   12

/* Campo TIPO: nibble bajo = tipo de trama, nibble alto = banderas. */
#define TIPO_DATOS      0x00
#define TIPO_ACK        0x01
#define TIPO_MASCARA    0x0F
#define BANDERA_PIDE_ACK 0x10

/* Secuencia de sincronizacion que precede a cada trama en la luz. */
#define FARO_PREAMBULO      0x55   /* 01010101: solo intervalos largos  */
#define FARO_BYTES_PREAMBULO 4
#define FARO_SFD            0xD5   /* 11010101: marca inicio de trama   */
#define FARO_PATRON_SYNC    0x55D5 /* ultimos 16 bits antes de la trama */

extern const uint8_t FARO_DIR_DIFUSION[FARO_DIR_LEN];

/* CRC-16/CCITT-FALSE: poly 0x1021, init 0xFFFF. "123456789" -> 0x29B1 */
uint16_t crc16(const uint8_t *datos, size_t n);
uint16_t crc16_continuar(uint16_t crc, const uint8_t *datos, size_t n);

/* Longitud total que debe tener una trama segun su campo LON. */
static inline uint16_t trama_longitud_total(uint8_t lon) {
    return (uint16_t)FARO_CABECERA + lon + FARO_CRC;
}

/* Arma una trama v1 en `salida` (al menos FARO_MAX_TRAMA bytes).
 * Devuelve la longitud total o 0 si la carga no cabe. */
uint8_t trama_armar(uint8_t *salida, uint8_t tipo, uint8_t seq,
                    const uint8_t *dst, const uint8_t *src,
                    const uint8_t *carga, uint8_t lon);

/* Verifica que la longitud sea coherente con LON y que el CRC coincida. */
bool trama_crc_valido(const uint8_t *trama, uint8_t n);
bool trama_longitud_valida(const uint8_t *trama, uint8_t n);

/* COBS: codifica `n` bytes; la salida necesita n + n/254 + 1 bytes.
 * No agrega el delimitador 0x00. Devuelve la longitud codificada. */
size_t cobs_codificar(const uint8_t *entrada, size_t n, uint8_t *salida);
/* Devuelve la longitud decodificada o 0 si la entrada es invalida. */
size_t cobs_decodificar(const uint8_t *entrada, size_t n, uint8_t *salida);

/* ------------------------------------------------------------------ */
/* Decodificador Manchester (IEEE 802.3: 0 = alto->bajo, 1 = bajo->alto)*/
/*                                                                     */
/* Se alimenta con cada flanco de la senal del receptor: el tiempo en  */
/* microsegundos desde el flanco anterior y el nivel despues del       */
/* flanco. Corre dentro de la interrupcion del pin RX.                 */
/* ------------------------------------------------------------------ */
enum EstadoRx : uint8_t {
    RX_CAZANDO = 0,     /* esperando un preambulo                    */
    RX_SINCRONIZADO,    /* alineado a mitad de bit, buscando SFD      */
    RX_RECIBIENDO,      /* leyendo bytes de la trama                  */
    RX_LISTA            /* trama completa, esperando que la lean      */
};

struct DecodificadorManchester {
    /* Configuracion */
    uint16_t medio_bit_us;

    /* Estado (lo modifica la ISR) */
    volatile uint8_t estado;
    uint8_t corrida_largos;   /* intervalos largos seguidos al cazar   */
    uint8_t esperando_corto;  /* vimos un flanco de frontera de bit    */
    uint8_t invertido;        /* polaridad detectada con el SFD        */
    uint8_t bits_sin_sfd;
    uint16_t registro;
    uint8_t byte_actual;
    uint8_t bits_en_byte;
    uint8_t esperados;
    volatile uint8_t longitud;
    uint8_t buf[FARO_MAX_TRAMA];

    void configurar(uint16_t bits_por_segundo);
    void reiniciar();
    /* dt_us: tiempo desde el flanco anterior; nivel: 0/1 tras el flanco */
    void flanco(uint16_t dt_us, uint8_t nivel);

private:
    void bit_recibido(uint8_t nivel);
};

#endif
