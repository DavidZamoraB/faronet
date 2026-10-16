/*
 * Pruebas de faro_core en la PC (sin Arduino).
 *
 *   g++ -std=c++11 -Wall -I.. test_core.cpp ../faro_core.cpp -o test_core && ./test_core
 *
 * Simula la forma de onda que emite el Faro (Manchester con preambulo y
 * SFD), le agrega desfase de reloj y ruido de temporizacion, y verifica
 * que el decodificador recupere la trama exacta.
 */
#include "../faro_core.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vector>

static int fallos = 0;
#define VERIFICAR(c, msg) do { if (!(c)) { printf("FALLO: %s (linea %d)\n", msg, __LINE__); fallos++; } } while (0)

/* Lista de niveles por medio bit, igual que emitir_trama() del firmware. */
static std::vector<uint8_t> medios_bits(const uint8_t *trama, size_t n) {
    std::vector<uint8_t> v;
    auto byte = [&](uint8_t b) {
        for (int i = 7; i >= 0; i--) {
            uint8_t bit = (b >> i) & 1;
            v.push_back(bit ? 0 : 1);
            v.push_back(bit ? 1 : 0);
        }
    };
    for (int i = 0; i < FARO_BYTES_PREAMBULO; i++) byte(FARO_PREAMBULO);
    byte(FARO_SFD);
    for (size_t i = 0; i < n; i++) byte(trama[i]);
    v.push_back(0); /* el emisor se apaga al terminar */
    return v;
}

/* Convierte niveles en flancos y los pasa al decodificador.
 * escala: desfase de reloj (1.05 = emisor 5% mas lento).
 * ruido: +- microsegundos aleatorios en cada flanco. */
static bool decodificar(DecodificadorManchester &d, const std::vector<uint8_t> &niveles,
                        uint16_t medio_us, double escala, int ruido, bool invertir) {
    uint8_t anterior = invertir ? 1 : 0; /* reposo: LED apagado */
    double t = 10000, ultimo = 0;
    for (size_t i = 0; i < niveles.size(); i++) {
        uint8_t nivel = invertir ? !niveles[i] : niveles[i];
        if (nivel != anterior) {
            double jitter = ruido ? (rand() % (2 * ruido + 1)) - ruido : 0;
            double ahora = t + jitter;
            double dt = ahora - ultimo;
            d.flanco(dt > 65535 ? 65535 : (uint16_t)dt, nivel);
            ultimo = ahora;
            anterior = nivel;
        }
        t += medio_us * escala;
    }
    return d.estado == RX_LISTA;
}

static void prueba_crc() {
    const uint8_t v[] = "123456789";
    VERIFICAR(crc16(v, 9) == 0x29B1, "CRC-16/CCITT-FALSE de \"123456789\"");
}

static void prueba_cobs() {
    uint8_t entrada[300], cod[310], dec[310];
    for (int caso = 0; caso < 200; caso++) {
        size_t n = 1 + rand() % 280;
        for (size_t i = 0; i < n; i++) entrada[i] = (rand() % 4 == 0) ? 0 : rand();
        size_t c = cobs_codificar(entrada, n, cod);
        for (size_t i = 0; i < c; i++) VERIFICAR(cod[i] != 0, "COBS sin ceros");
        size_t m = cobs_decodificar(cod, c, dec);
        VERIFICAR(m == n && memcmp(entrada, dec, n) == 0, "COBS ida y vuelta");
    }
    const uint8_t malo[] = {0x05, 0x11, 0x22};
    VERIFICAR(cobs_decodificar(malo, 3, dec) == 0, "COBS rechaza codigo que se pasa del final");
}

static void prueba_trama() {
    uint8_t dst[4] = {1, 2, 3, 4}, src[4] = {9, 8, 7, 6}, carga[FARO_MAX_CARGA + 1];
    uint8_t t[FARO_MAX_TRAMA];
    for (int i = 0; i <= FARO_MAX_CARGA; i++) carga[i] = i * 7;
    uint8_t n = trama_armar(t, TIPO_DATOS | BANDERA_PIDE_ACK, 42, dst, src, carga, FARO_MAX_CARGA);
    VERIFICAR(n == FARO_MAX_TRAMA, "trama maxima mide 128");
    VERIFICAR(trama_crc_valido(t, n), "CRC valido");
    t[20] ^= 0x01;
    VERIFICAR(!trama_crc_valido(t, n), "CRC detecta un bit cambiado");
    VERIFICAR(trama_armar(t, 0, 0, dst, src, carga, FARO_MAX_CARGA + 1) == 0, "carga demasiado grande");
}

static void prueba_manchester() {
    uint8_t dst[4] = {0xAA, 0xBB, 0xCC, 0xDD}, src[4] = {1, 2, 3, 4}, carga[FARO_MAX_CARGA];
    uint8_t t[FARO_MAX_TRAMA];
    const uint16_t velocidades[] = {1000, 2000, 4000, 8000};
    const double escalas[] = {1.0, 0.92, 1.08};
    const int ruidos[] = {0, 8};
    int casos = 0;

    for (uint16_t bps : velocidades) {
        uint16_t medio = 500000 / bps;
        for (double escala : escalas) {
            for (int ruido : ruidos) {
                if (ruido >= medio / 4) continue;
                for (int inv = 0; inv < 2; inv++) {
                    for (int lon : {0, 1, 57, FARO_MAX_CARGA}) {
                        for (int i = 0; i < lon; i++) carga[i] = rand();
                        uint8_t n = trama_armar(t, TIPO_DATOS, lon, dst, src, carga, lon);
                        DecodificadorManchester d;
                        d.configurar(bps);
                        bool ok = decodificar(d, medios_bits(t, n), medio, escala, ruido, inv);
                        char msg[128];
                        snprintf(msg, sizeof msg, "decodifica bps=%u escala=%.2f ruido=%d inv=%d lon=%d",
                                 bps, escala, ruido, inv, lon);
                        VERIFICAR(ok && d.longitud == n && memcmp(d.buf, t, n) == 0, msg);
                        VERIFICAR(ok && trama_crc_valido(d.buf, d.longitud), msg);
                        casos++;
                    }
                }
            }
        }
    }
    printf("  %d casos Manchester\n", casos);

    /* Velocidad equivocada: no debe "inventar" una trama. */
    uint8_t n = trama_armar(t, TIPO_DATOS, 0, dst, src, carga, 30);
    DecodificadorManchester d;
    d.configurar(2000);
    VERIFICAR(!decodificar(d, medios_bits(t, n), 500000 / 4000, 1.0, 0, false),
              "no decodifica a otra velocidad");

    /* Ruido puro (flancos aleatorios) no produce tramas con CRC valido. */
    int falsas = 0;
    d.configurar(2000);
    for (int i = 0; i < 200000; i++) {
        d.flanco(50 + rand() % 900, rand() & 1);
        if (d.estado == RX_LISTA) {
            if (trama_crc_valido(d.buf, d.longitud)) falsas++;
            d.reiniciar();
        }
    }
    VERIFICAR(falsas == 0, "el ruido no genera tramas validas");

    /* Dos tramas seguidas: tras leer la primera, la segunda tambien llega. */
    d.configurar(2000);
    VERIFICAR(decodificar(d, medios_bits(t, n), 250, 1.0, 0, false), "primera trama");
    d.reiniciar();
    VERIFICAR(decodificar(d, medios_bits(t, n), 250, 1.0, 0, false), "segunda trama");
}

int main() {
    srand(1234);
    prueba_crc();
    prueba_cobs();
    prueba_trama();
    prueba_manchester();
    if (fallos) {
        printf("%d fallos\n", fallos);
        return 1;
    }
    printf("OK: todas las pruebas de faro_core pasaron\n");
    return 0;
}
