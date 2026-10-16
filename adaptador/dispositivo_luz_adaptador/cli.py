"""Cliente de terminal del Faro.

    python -m dispositivo_luz_adaptador -p /dev/ttyUSB0 info
    python -m dispositivo_luz_adaptador -p /dev/ttyUSB0 enviar a1:b2:c3:d4 "hola"
    python -m dispositivo_luz_adaptador -p /dev/ttyUSB0 escuchar
    python -m dispositivo_luz_adaptador -p /dev/ttyUSB0 medir receptor --tramas 200 --distancia 50cm
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from . import medicion
from .adaptador import DispositivoLuzAdaptador, ErrorFaro
from .trama import MAX_CARGA, ErrorTrama, formatear_direccion, parsear_direccion


def _si_no(texto: str) -> bool:
    if texto.lower() in ("si", "sí", "on", "1", "true"):
        return True
    if texto.lower() in ("no", "off", "0", "false"):
        return False
    raise argparse.ArgumentTypeError("use si/no")


def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="faro", description="Cliente del Faro (DispositivoLuzAdaptador)")
    p.add_argument("-p", "--puerto", required=True, help="puerto serial, p. ej. /dev/ttyUSB0")
    p.add_argument("-b", "--baudios", type=int, default=115200)
    sub = p.add_subparsers(dest="comando", required=True)

    sub.add_parser("info", help="direccion, velocidad y opciones del Faro")
    sub.add_parser("estadisticas", help="contadores de tramas")

    e = sub.add_parser("enviar", help="enviar un mensaje por la luz")
    e.add_argument("destino", help="a1:b2:c3:d4 o 'difusion'")
    e.add_argument("mensaje", help="texto (o hex con --hex)")
    e.add_argument("--hex", action="store_true", help="el mensaje viene en hexadecimal")
    e.add_argument("--sin-ack", action="store_true", help="no pedir confirmacion")

    c = sub.add_parser("enviar-cruda", help="transmitir una trama completa armada afuera (hex)")
    c.add_argument("trama_hex")

    s = sub.add_parser("escuchar", help="mostrar las tramas que llegan")
    s.add_argument("--promiscuo", action="store_true", help="mostrar tambien tramas ajenas")

    cf = sub.add_parser("configurar", help="cambiar velocidad y opciones")
    cf.add_argument("--bps", type=int, help=f"bits por segundo en la luz (500-20000)")
    cf.add_argument("--reintentos", type=int)
    cf.add_argument("--promiscuo", type=_si_no)
    cf.add_argument("--entregar-crc-malo", type=_si_no)

    d = sub.add_parser("direccion", help="fijar o rotar la direccion fisica")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--rotar", action="store_true", help="direccion aleatoria nueva")
    g.add_argument("--fijar", metavar="DIR")

    sc = sub.add_parser("secreto", help="secreto de 32 bytes guardado en el Faro")
    g = sc.add_mutually_exclusive_group(required=True)
    g.add_argument("--generar", action="store_true", help="generar y guardar uno nuevo")
    g.add_argument("--estado", action="store_true", help="indicar si hay uno guardado")

    sub.add_parser("panico", help="borrar secreto y direccion (igual que el boton)")

    so = sub.add_parser("sondear", help="leer el sensor para calibrar el trimpot")
    so.add_argument("--continuo", action="store_true")

    em = sub.add_parser("emisor", help="LED IR fijo encendido/apagado (para el multimetro)")
    em.add_argument("estado", choices=["encender", "apagar"])

    m = sub.add_parser("medir", help="medir tasa efectiva y BER entre dos Faros")
    m.add_argument("rol", choices=["emisor", "receptor"])
    m.add_argument("--tramas", type=int, default=100)
    m.add_argument("--tam", type=int, default=MAX_CARGA, help=f"bytes de carga (2-{MAX_CARGA})")
    m.add_argument("--distancia", default="?", help="etiqueta para el CSV, p. ej. 50cm")
    m.add_argument("--csv", help="agregar el resultado a este archivo CSV")
    return p


def _mostrar(rec) -> None:
    t = rec.trama
    if t is None:
        print(f"[CRC MALO] {rec.crudo.hex()}")
        return
    texto = t.carga.decode("utf-8", errors="replace")
    print(f"{t}  {texto!r}")


def ejecutar(args) -> int:
    with DispositivoLuzAdaptador(args.puerto, args.baudios) as faro:
        if args.comando == "info":
            fw = faro.ping()
            print(f"firmware {fw.version_firmware}, protocolo v{fw.version_protocolo}, "
                  f"trama maxima {fw.max_trama} B")
            print(faro.info())
        elif args.comando == "estadisticas":
            for k, v in vars(faro.estadisticas()).items():
                print(f"{k:16} {v}")
        elif args.comando == "enviar":
            datos = bytes.fromhex(args.mensaje) if args.hex else args.mensaje.encode()
            r = faro.enviar(parsear_direccion(args.destino), datos, pedir_ack=not args.sin_ack)
            print(r)
            return 0 if r.ok else 1
        elif args.comando == "enviar-cruda":
            r = faro.enviar_trama(bytes.fromhex(args.trama_hex))
            print(r)
            return 0 if r.ok else 1
        elif args.comando == "escuchar":
            anterior = faro.info().promiscuo
            if args.promiscuo:
                faro.configurar(promiscuo=True)
            faro.al_panico(lambda d: print(f"!! PANICO: nueva direccion {formatear_direccion(d)}"))
            print(f"escuchando como {formatear_direccion(faro.direccion)} (Ctrl+C para salir)")
            try:
                while True:
                    rec = faro.recibir(timeout=0.5)
                    if rec:
                        _mostrar(rec)
            except KeyboardInterrupt:
                pass
            finally:
                if args.promiscuo:
                    faro.configurar(promiscuo=anterior)
        elif args.comando == "configurar":
            print(faro.configurar(bps=args.bps, promiscuo=args.promiscuo,
                                  entregar_crc_malo=args.entregar_crc_malo,
                                  reintentos=args.reintentos))
        elif args.comando == "direccion":
            nueva = faro.rotar_direccion() if args.rotar else faro.fijar_direccion(args.fijar)
            print(f"direccion: {formatear_direccion(nueva)}")
        elif args.comando == "secreto":
            if args.generar:
                faro.guardar_secreto(os.urandom(32))
                print("secreto nuevo guardado en el Faro")
            else:
                print("hay secreto guardado" if faro.info().secreto_presente else "no hay secreto")
        elif args.comando == "panico":
            faro.panico()
            time.sleep(1.5)
            print(faro.info())
        elif args.comando == "sondear":
            try:
                while True:
                    a, d = faro.sondear()
                    barra = "#" * (a * 50 // 1023)
                    print(f"\ranalogico {a:4d} {barra:<50} comparador={d}", end="", flush=True)
                    if not args.continuo:
                        break
                    time.sleep(0.1)
            except KeyboardInterrupt:
                pass
            print()
        elif args.comando == "emisor":
            a, d = faro.emisor_fijo(args.estado == "encender")
            print(f"LED IR {args.estado == 'encender' and 'ENCENDIDO' or 'apagado'}; "
                  f"sensor propio: analogico={a} comparador={d}")
        elif args.comando == "medir":
            bps = faro.info().bps
            if args.rol == "emisor":
                r = medicion.emisor(faro, args.tramas, args.tam)
                print(f"enviadas {r.enviadas_ok}/{r.tramas} en {r.segundos:.2f} s "
                      f"-> {r.tasa_bps:.1f} bit/s de carga")
            else:
                print(f"esperando {args.tramas} tramas de {args.tam} B a {bps} bps...")
                r = medicion.receptor(faro, args.tramas, args.tam)
                print(r.resumen())
                if args.csv:
                    medicion.guardar_csv(args.csv, args.distancia, bps, args.tam, r)
                    print(f"guardado en {args.csv}")
    return 0


def main(argv=None) -> int:
    args = construir_parser().parse_args(argv)
    try:
        return ejecutar(args)
    except (ErrorFaro, ErrorTrama, ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
