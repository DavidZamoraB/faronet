"""Loopback de un Faro manejado por una Raspberry Pi: emite tramas y las lee
con su propio sensor (el reflejo en una superficie cercana).

Mide tramas buenas, con errores y perdidas, el BER y la tasa efectiva, con un
solo Faro (no hace falta el segundo). Correr en la Raspberry:

    python hardware/loopback_gpio.py                     # 50 tramas de 100 B a 2000 bit/s
    python hardware/loopback_gpio.py --tramas 200 --tam 114 --bps 1000

Ponga una hoja blanca (o el mantel) a 1-2 cm del LED IR y del sensor.
"""
import argparse
import sys

from dispositivo_luz_adaptador.faro_gpio import FaroGPIO, probar_loopback


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--puerto", default="gpio", help="gpio[:pines][@host] (por defecto: gpio)")
    p.add_argument("--tramas", type=int, default=50)
    p.add_argument("--tam", type=int, default=100, help="bytes de carga por trama (1 a 114)")
    p.add_argument("--bps", type=int, default=2000)
    args = p.parse_args()

    faro = FaroGPIO.desde_texto(args.puerto, bps=args.bps)
    try:
        def avance(i, ok, mal, perdidas):
            print(f"\r{i}/{args.tramas}  buenas={ok}  con_errores={mal}  perdidas={perdidas}",
                  end="", flush=True)
        r = probar_loopback(faro, args.tramas, args.tam, al_avanzar=avance)
    finally:
        faro.close()
    print()
    ber = "sin datos (no llego ninguna trama completa)" if r["ber"] is None else f"{r['ber']:.2e}"
    print(f"velocidad de linea : {r['bps']} bit/s")
    print(f"tramas             : {r['ok']} buenas, {r['con_errores']} con errores, {r['perdidas']} perdidas (de {r['tramas']})")
    print(f"BER                : {ber}  ({r['bits_erroneos']} de {r['bits_comparados']} bits)")
    print(f"tasa efectiva      : {r['tasa_efectiva_bps']:.0f} bit/s de carga util en {r['segundos']:.1f} s")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
