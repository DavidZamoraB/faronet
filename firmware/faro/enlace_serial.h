/*
 * enlace_serial.h - Protocolo entre el nodo (PC/RPi) y el Faro por USB-serial.
 *
 * Cada paquete viaja como COBS(TIPO | DATOS | CRC16) seguido de 0x00.
 * El CRC16 (big endian) cubre TIPO y DATOS. Debe coincidir con
 * adaptador/dispositivo_luz_adaptador/enlace.py.
 */
#ifndef ENLACE_SERIAL_H
#define ENLACE_SERIAL_H

#define ENLACE_BAUDIOS 115200

/* Version del firmware que reporta PONG */
#define FW_VERSION_MAYOR 1
#define FW_VERSION_MENOR 0

/* Comandos nodo -> Faro */
#define CMD_PING                0x01
#define CMD_INFO                0x02
#define CMD_ENVIAR              0x03  /* DST(4) BANDERAS(1) CARGA(n)            */
#define CMD_ENVIAR_CRUDA        0x04  /* TRAMA completa armada fuera del Faro   */
#define CMD_FIJAR_DIRECCION     0x05  /* DIR(4)                                 */
#define CMD_ROTAR_DIRECCION     0x06
#define CMD_CONFIGURAR          0x07  /* BPS(2) OPCIONES(1) REINTENTOS(1)        */
#define CMD_ESTADISTICAS        0x08
#define CMD_REINICIAR_ESTAD     0x09
#define CMD_GUARDAR_SECRETO     0x0A  /* SECRETO(32)                            */
#define CMD_LEER_SECRETO        0x0B
#define CMD_PANICO              0x0C
#define CMD_SONDEAR             0x0D
#define CMD_EMISOR_FIJO         0x0E  /* ESTADO(1): LED IR fijo para medir      */

/* Respuestas Faro -> nodo */
#define RSP_PONG                0x81  /* FW_MAYOR FW_MENOR VER_PROTO MAX_TRAMA   */
#define RSP_INFO                0x82  /* DIR(4) BPS(2) OPCIONES REINTENTOS SECRETO */
#define RSP_RESULTADO_TX        0x83  /* ESTADO INTENTOS SEQ                    */
#define RSP_DIRECCION           0x85  /* DIR(4)                                 */
#define RSP_ESTADISTICAS        0x88  /* 6 x uint32 big endian                  */
#define RSP_SECRETO_GUARDADO    0x8A
#define RSP_SECRETO             0x8B  /* SECRETO(32)                            */
#define RSP_SONDEO              0x8D  /* ANALOGICO(2) DIGITAL(1)                */

/* Eventos asincronos Faro -> nodo */
#define EVT_PANICO              0x8C  /* DIR_NUEVA(4)                           */
#define EVT_TRAMA_RECIBIDA      0x90  /* CRC_OK(1) TRAMA(n)                     */
#define RSP_ERROR               0xFF  /* CODIGO                                 */

/* Codigos de error */
#define ERR_COMANDO_DESCONOCIDO 0x01
#define ERR_LONGITUD            0x02
#define ERR_CRC_ENLACE          0x03
#define ERR_PARAMETRO           0x04
#define ERR_SIN_SECRETO         0x05

/* Estados de RSP_RESULTADO_TX */
#define TX_OK                   0x00
#define TX_SIN_ACK              0x01
#define TX_CANAL_OCUPADO        0x02
#define TX_TRAMA_INVALIDA       0x03
#define TX_ABORTADO_PANICO      0x04

/* Bits de OPCIONES */
#define OPC_PROMISCUO           0x01  /* entregar tramas para otras direcciones */
#define OPC_ENTREGAR_CRC_MALO   0x02  /* entregar tramas con CRC malo (BER)     */

#define SECRETO_LEN 32

#endif
