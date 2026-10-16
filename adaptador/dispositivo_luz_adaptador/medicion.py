"""Medicion de tasa de transferencia efectiva y BER entre dos Faros.

Un Faro corre `emisor()` y el otro `receptor()` con los mismos parametros.
El emisor manda `n` tramas de difusion sin ACK cuya carga es pseudoaleatoria
y depende solo del indice, asi el receptor sabe que bytes debieron llegar y
cuenta los bits errados (incluso en tramas con CRC malo).
"""
from __future__ import annotations

import csv
import os
import random
import time
from dataclasses import asdict, dataclass

from .adaptador import DispositivoLuzAdaptador
from .trama import DIFUSION, MAX_CARGA


def carga_de_prueba(indice: int, tam: int) -> bytes:
    azar = random.Random(indice)
    return indice.to_bytes(2, "big") + bytes(azar.getrandbits(8) for _ in range(tam - 2))


def _bits_errados(recibida: bytes, esperada: bytes) -> int:
    n = min(len(recibida), len(esperada))
    errados = sum(bin(a ^ b).count("1") for a, b in zip(recibida[:n], esperada[:n]))
    return errados + 8 * abs(len(esperada) - len(recibida))


@dataclass
class ResultadoEmisor:
    tramas: int
    enviadas_ok: int
    bytes_carga: int
    segundos: float

    @property
    def tasa_bps(self) -> float:
        return self.bytes_carga * 8 / self.segundos if self.segundos else 0.0


@dataclass
class ResultadoReceptor:
    esperadas: int
    recibidas: int
    crc_ok: int
    bits_comparados: int
    bits_errados: int
    bytes_utiles: int
    segundos: float

    @property
    def ber(self) -> float:
        return self.bits_errados / self.bits_comparados if self.bits_comparados else float("nan")

    @property
    def perdidas(self) -> int:
        return self.esperadas - self.recibidas

    @property
    def tasa_efectiva_bps(self) -> float:
        return self.bytes_utiles * 8 / self.segundos if self.segundos else 0.0

    def resumen(self) -> str:
        return (f"tramas: {self.recibidas}/{self.esperadas} recibidas, {self.crc_ok} con CRC correcto\n"
                f"BER: {self.ber:.2e} ({self.bits_errados} de {self.bits_comparados} bits)\n"
                f"tasa efectiva: {self.tasa_efectiva_bps:.1f} bit/s de carga util "
                f"({self.segundos:.2f} s)")


def emisor(faro: DispositivoLuzAdaptador, tramas: int = 100, tam: int = MAX_CARGA,
           destino: bytes = DIFUSION, pedir_ack: bool = False) -> ResultadoEmisor:
    if not 2 <= tam <= MAX_CARGA:
        raise ValueError(f"tam debe estar entre 2 y {MAX_CARGA}")
    ok = 0
    inicio = time.monotonic()
    for i in range(tramas):
        if faro.enviar(destino, carga_de_prueba(i, tam), pedir_ack=pedir_ack).ok:
            ok += 1
    return ResultadoEmisor(tramas, ok, ok * tam, time.monotonic() - inicio)


def receptor(faro: DispositivoLuzAdaptador, tramas: int = 100, tam: int = MAX_CARGA,
             espera_inicial: float = 60.0, inactividad: float = 5.0) -> ResultadoReceptor:
    anterior = faro.info()
    faro.configurar(entregar_crc_malo=True)
    vistas: set[int] = set()
    r = ResultadoReceptor(tramas, 0, 0, 0, 0, 0, 0.0)
    primera = ultima = None
    ultimo_indice = -1
    try:
        while len(vistas) < tramas:
            rec = faro.recibir(timeout=espera_inicial if primera is None else inactividad)
            if rec is None:
                break
            carga = rec.crudo[12:-2]
            if len(carga) < 2:
                continue
            indice = int.from_bytes(carga[:2], "big")
            if not rec.crc_ok:
                # El indice mismo pudo llegar corrupto: entre el leido y el
                # siguiente al anterior, nos quedamos con el que explique la
                # carga con menos bits errados.
                candidatos = {i for i in (indice, ultimo_indice + 1)
                              if 0 <= i < tramas and i not in vistas}
                if not candidatos:
                    continue
                indice = min(candidatos, key=lambda i: _bits_errados(carga, carga_de_prueba(i, tam)))
            if indice >= tramas or indice in vistas:
                continue
            vistas.add(indice)
            ultimo_indice = indice
            esperada = carga_de_prueba(indice, tam)
            errados = _bits_errados(carga, esperada)
            r.recibidas += 1
            r.bits_comparados += 8 * len(esperada)
            r.bits_errados += errados
            if rec.crc_ok:
                r.crc_ok += 1
                r.bytes_utiles += tam
            primera = primera or rec.recibida_en
            ultima = rec.recibida_en
    finally:
        faro.configurar(entregar_crc_malo=anterior.entregar_crc_malo)
    if primera is not None and ultima is not None and r.recibidas > 1:
        # La primera trama marca el inicio; su carga no cuenta en la tasa.
        r.segundos = ultima - primera
        r.bytes_utiles = max(0, r.bytes_utiles - tam)
    return r


def guardar_csv(ruta: str, distancia: str, bps: int, tam: int, r: ResultadoReceptor) -> None:
    nuevo = not os.path.exists(ruta)
    with open(ruta, "a", newline="") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["distancia", "bps_linea", "tam_carga", *asdict(r).keys(),
                        "ber", "tasa_efectiva_bps"])
        w.writerow([distancia, bps, tam, *asdict(r).values(),
                    f"{r.ber:.3e}", f"{r.tasa_efectiva_bps:.1f}"])
