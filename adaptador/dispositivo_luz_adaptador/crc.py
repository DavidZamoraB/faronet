"""CRC-16/CCITT-FALSE, igual al de firmware/faro/faro_core.cpp."""


def crc16(datos: bytes, crc: int = 0xFFFF) -> int:
    """poly 0x1021, init 0xFFFF, sin reflejar. crc16(b"123456789") == 0x29B1."""
    for b in datos:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
