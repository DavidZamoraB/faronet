"""Cliente de terminal de FaroNet.

    faronet --llave yo.key --escuchar 0.0.0.0:9001 --vecino 192.168.1.20:9001 --nombre ana
    faronet --faro /dev/ttyUSB0 --escuchar 0.0.0.0:9001 --nombre gateway-norte
    faronet --llave gw.key --gateway --edge https://faronet.<cuenta>.workers.dev --escuchar 0.0.0.0:9101

Abre una consola con los comandos: nodos, rutas, circuitos, enviar, buzon,
panico, salir.
"""
from __future__ import annotations

import argparse
import os
import shlex
import sys
import threading

from .cripto import SEMILLA_LEN, Identidad
from .directorio import ROL_GATEWAY, ROL_RELE
from .enlaces import EnlaceTCP, ServidorTCP, parsear_host_puerto
from .mensaje import Mensaje
from .nodo import ErrorNodo, Nodo
from .onion import MAX_SALTOS, MIN_SALTOS

AYUDA = """comandos:
  nodos                     directorio de nodos conocidos
  rutas                     tabla de rutas (destino, metrica, enlace)
  circuitos                 circuitos que este nodo esta releyando
  enviar <nombre|id> <texto>  mensaje privado anonimo
  publicar <tema> <texto>   mensaje publico (sale a clearnet por un gateway)
  buzon                     mensajes recibidos (con TTL)
  panico                    borra llaves y estado, y termina
  salir"""


def _argumentos(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="faronet", description="Nodo de la mesh anonima FaroNet")
    p.add_argument("--llave", help="archivo con la semilla de 32 bytes (se crea si no existe)")
    p.add_argument("--faro", action="append", default=[], metavar="PUERTO",
                   help="puerto serial de un Faro (repetible); sin --llave, la identidad "
                        "se guarda en el Faro y el boton de panico la borra")
    p.add_argument("--bps", type=int, help="velocidad de los Faros (ambos extremos iguales)")
    p.add_argument("--rotar-direccion", type=float, default=600, metavar="SEG",
                   help="rotar la direccion fisica del Faro cada SEG segundos (0 = nunca)")
    p.add_argument("--escuchar", metavar="HOST:PUERTO", help="aceptar vecinos por TCP")
    p.add_argument("--vecino", action="append", default=[], metavar="HOST:PUERTO",
                   help="conectarse a un vecino por TCP (repetible)")
    p.add_argument("--nombre", default="", help="seudonimo publicado en el directorio")
    p.add_argument("--alias", default="", help="alias que acompana los mensajes enviados")
    p.add_argument("--gateway", action="store_true", help="anunciarse como gateway")
    p.add_argument("--edge", metavar="URL",
                   help="URL del Worker: este gateway publica ahi los mensajes publicos "
                        "y el directorio (requiere --gateway y el paquete faronet-gateway)")
    p.add_argument("--saltos", type=int, default=MIN_SALTOS, choices=range(MIN_SALTOS, MAX_SALTOS + 1))
    p.add_argument("--intervalo-rutas", type=float, default=10.0, metavar="SEG")
    p.add_argument("--sin-consola", action="store_true", help="solo releyar (servicio)")
    return p.parse_args(argv)


def _identidad_de_archivo(ruta: str) -> Identidad:
    if os.path.exists(ruta):
        with open(ruta, "rb") as f:
            semilla = f.read()
        if len(semilla) != SEMILLA_LEN:
            sys.exit(f"{ruta}: la llave debe medir {SEMILLA_LEN} bytes")
        return Identidad(semilla)
    identidad = Identidad.nueva()
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(identidad.semilla)
    print(f"nueva identidad guardada en {ruta}")
    return identidad


def _identidad_de_faro(faro) -> Identidad:
    semilla = faro.leer_secreto()
    if semilla is None or len(semilla) != SEMILLA_LEN:
        identidad = Identidad.nueva()
        faro.guardar_secreto(identidad.semilla)
        print("nueva identidad guardada en el Faro")
        return identidad
    return Identidad(semilla)


def _borrar_archivo(ruta: str) -> None:
    try:
        largo = os.path.getsize(ruta)
        with open(ruta, "r+b") as f:
            f.write(os.urandom(largo))
            f.flush()
            os.fsync(f.fileno())
        os.remove(ruta)
    except OSError:
        pass


def main(argv=None) -> int:
    args = _argumentos(argv)
    if not args.llave and not args.faro:
        sys.exit("indique --llave ARCHIVO o --faro PUERTO para la identidad del nodo")

    faros = []
    if args.faro:
        from dispositivo_luz_adaptador import DispositivoLuzAdaptador

        for puerto in args.faro:
            faro = DispositivoLuzAdaptador(puerto).abrir()
            if args.bps:
                faro.configurar(bps=args.bps)
            faro.rotar_direccion()
            if args.rotar_direccion > 0:
                faro.rotacion_automatica(args.rotar_direccion)
            faros.append(faro)

    identidad = _identidad_de_archivo(args.llave) if args.llave else _identidad_de_faro(faros[0])
    roles = ROL_RELE | (ROL_GATEWAY if args.gateway else 0)
    nodo = Nodo(identidad, args.nombre, roles, args.intervalo_rutas, args.saltos)
    terminar = threading.Event()

    def panico(*_):
        nodo.panico()
        if args.llave:
            _borrar_archivo(args.llave)
        print("\n*** PANICO: llaves y estado borrados ***", flush=True)
        terminar.set()
        os._exit(1)

    def al_mensaje(m: Mensaje):
        de = m.alias or "anonimo"
        print(f"\n[mensaje de {de}] {m.texto}\n> ", end="", flush=True)

    nodo.al_mensaje.append(al_mensaje)
    nodo.iniciar()

    from .enlaces import EnlaceFaro

    for faro in faros:
        faro.al_panico(panico)
        nodo.agregar_enlace(EnlaceFaro(faro))
    if args.edge:
        if not args.gateway:
            sys.exit("--edge requiere --gateway")
        try:
            from faronet_gateway.puente import Puente
        except ImportError:
            sys.exit("--edge requiere el paquete faronet-gateway (pip install -e gateway)")
        Puente(nodo, args.edge).iniciar()
    servidor = None
    if args.escuchar:
        host, puerto = parsear_host_puerto(args.escuchar)
        servidor = ServidorTCP(host, puerto, nodo.agregar_enlace)
    for vecino in args.vecino:
        try:
            nodo.agregar_enlace(EnlaceTCP.conectar(*parsear_host_puerto(vecino)))
        except OSError as e:
            print(f"no se pudo conectar a {vecino}: {e}")

    print(f"nodo {nodo.id.hex()} ({args.nombre or 'sin nombre'}) en marcha", flush=True)
    try:
        if args.sin_consola:
            terminar.wait()
        else:
            _consola(nodo, args, panico)
    except KeyboardInterrupt:
        pass
    finally:
        nodo.detener()
        if servidor:
            servidor.cerrar()
        for faro in faros:
            faro.cerrar()
    return 0


def _consola(nodo: Nodo, args, panico) -> None:
    print(AYUDA)
    while True:
        try:
            linea = input("> ").strip()
        except EOFError:
            return
        if not linea:
            continue
        try:
            partes = shlex.split(linea)
        except ValueError as e:
            print(e)
            continue
        cmd = partes[0]
        if cmd == "salir":
            return
        if cmd == "nodos":
            for e in sorted(nodo.directorio.entradas(), key=lambda e: e.nombre):
                roles = "+".join(r for r, b in (("rele", ROL_RELE), ("gateway", ROL_GATEWAY)) if e.es(b))
                yo = "  (este nodo)" if e.id == nodo.id else ""
                print(f"  {e.id.hex()}  {e.nombre or '-':16} {roles}{yo}")
        elif cmd == "rutas":
            for destino, (metrica, enlace) in nodo.rutas.destinos().items():
                print(f"  {destino.hex()}  metrica={metrica:2}  via {enlace}")
        elif cmd == "circuitos":
            for t in nodo.tramos():
                sig = t.siguiente.hex() if t.siguiente else "(salida)"
                print(f"  salto {t.posicion}: {t.anterior.hex()} -> {sig}")
        elif cmd == "enviar" and len(partes) >= 3:
            try:
                nodo.enviar_mensaje(partes[1], " ".join(partes[2:]), args.alias)
                print("entregado a la salida del circuito")
            except (ErrorNodo, ValueError) as e:
                print(f"error: {e}")
        elif cmd == "publicar" and len(partes) >= 3:
            try:
                nodo.publicar(partes[1], " ".join(partes[2:]), args.alias)
                print(f"publicado en #{partes[1]}")
            except (ErrorNodo, ValueError) as e:
                print(f"error: {e}")
        elif cmd == "buzon":
            for m in nodo.buzon.mensajes():
                print(f"  [{m.alias or 'anonimo'}] {m.texto}")
        elif cmd == "panico":
            panico()
        else:
            print(AYUDA)


if __name__ == "__main__":
    sys.exit(main())
