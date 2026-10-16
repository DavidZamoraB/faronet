"""COBS (Consistent Overhead Byte Stuffing) para delimitar paquetes con 0x00."""


class ErrorCOBS(ValueError):
    pass


def codificar(datos: bytes) -> bytes:
    salida = bytearray([0])
    pos_codigo = 0
    codigo = 1
    for b in datos:
        if b == 0:
            salida[pos_codigo] = codigo
            pos_codigo = len(salida)
            salida.append(0)
            codigo = 1
        else:
            salida.append(b)
            codigo += 1
            if codigo == 0xFF:
                salida[pos_codigo] = codigo
                pos_codigo = len(salida)
                salida.append(0)
                codigo = 1
    salida[pos_codigo] = codigo
    return bytes(salida)


def decodificar(datos: bytes) -> bytes:
    salida = bytearray()
    i = 0
    while i < len(datos):
        codigo = datos[i]
        if codigo == 0 or i + codigo > len(datos):
            raise ErrorCOBS("paquete COBS invalido")
        bloque = datos[i + 1:i + codigo]
        if 0 in bloque:
            raise ErrorCOBS("byte 0 dentro de un paquete COBS")
        salida += bloque
        i += codigo
        if codigo != 0xFF and i != len(datos):
            salida.append(0)
    return bytes(salida)
