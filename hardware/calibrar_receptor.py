"""Prueba del umbral del receptor (divisor R9/R10 del LM393).

Alterna el LED IR propio cada medio segundo y muestra la lectura del sensor
y la salida del comparador en cada estado. El receptor esta bien cuando se ve:

    apagado: comparador 0   |   encendido: comparador 1   LISTO

Si no llega a LISTO, cambie R10 (ver hardware/esquematico.md).

Uso (con el LED IR apuntando al sensor, o una hoja blanca encima de ambos):

    python hardware/calibrar_receptor.py /dev/ttyACM0
"""
import statistics
import sys
import time

from dispositivo_luz_adaptador import DispositivoLuzAdaptador, ErrorFaro


def medir(faro, encendido: bool, n: int = 8) -> tuple[float, float]:
    faro.emisor_fijo(encendido)
    time.sleep(0.05)
    lecturas = [faro.sondear() for _ in range(n)]
    return statistics.median(a for a, _ in lecturas), sum(c for _, c in lecturas) / n


def main() -> None:
    puerto = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    with DispositivoLuzAdaptador(puerto) as faro:
        print("Objetivo: apagado -> 0, encendido -> 1.  Ctrl+C para salir.\n")
        try:
            while True:
                try:
                    a_off, c_off = medir(faro, False)
                    a_on, c_on = medir(faro, True)
                except ErrorFaro:
                    # Con el umbral justo en el borde, la salida del comparador
                    # oscila tan rapido que el Arduino pierde bytes del puerto.
                    print("\rOSCILANDO: el umbral esta justo en el borde de la senal, cambie R10"
                          + " " * 20, end="", flush=True)
                    time.sleep(0.3)
                    continue
                ok = c_off < 0.2 and c_on > 0.8
                estado = "LISTO" if ok else "  ...  "
                print(f"\rapagado: A0={a_off:4.0f} comp={round(c_off)}  |  encendido: A0={a_on:4.0f} "
                      f"comp={round(c_on)}   {estado}" + " " * 20, end="", flush=True)
        except KeyboardInterrupt:
            print()
        finally:
            try:
                faro.emisor_fijo(False)
            except ErrorFaro:
                pass


if __name__ == "__main__":
    main()
