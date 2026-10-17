"""Cliente de terminal del Worker.

    faronet-edge llave --llave gw.key                       llave publica para GATEWAYS
    faronet-edge --url URL publicar --llave gw.key general "hola"
    faronet-edge --url URL subir-directorio --llave gw.key  (entrada propia del gateway)
    faronet-edge --url URL directorio
    faronet-edge buzon secreto                              genera un secreto compartido
    faronet-edge --url URL buzon depositar SECRETO "texto" [--ttl SEG]
    faronet-edge --url URL buzon retirar SECRETO
"""
from __future__ import annotations

import argparse
import os
import sys

from faronet.cripto import SEMILLA_LEN, Identidad
from faronet.directorio import ROL_GATEWAY, ROL_RELE, Entrada

from . import edge

URL_DEFECTO = os.environ.get("FARONET_EDGE_URL", "http://127.0.0.1:8787")


def _identidad(ruta: str) -> Identidad:
    with open(ruta, "rb") as f:
        semilla = f.read()
    if len(semilla) != SEMILLA_LEN:
        sys.exit(f"{ruta}: la llave debe medir {SEMILLA_LEN} bytes")
    return Identidad(semilla)


def _secreto(texto: str) -> bytes:
    try:
        s = bytes.fromhex(texto)
    except ValueError:
        s = b""
    if len(s) != 32:
        sys.exit("el secreto son 32 bytes en hex (genere uno con: faronet-edge buzon secreto)")
    return s


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="faronet-edge", description="Cliente del Worker de FaroNet")
    p.add_argument("--url", default=URL_DEFECTO, help=f"URL del Worker (defecto {URL_DEFECTO})")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("llave", help="muestra la llave publica del gateway")
    s.add_argument("--llave", required=True)
    s = sub.add_parser("publicar", help="publica en una sala publica")
    s.add_argument("--llave", required=True)
    s.add_argument("--alias", default="")
    s.add_argument("tema")
    s.add_argument("texto")
    s = sub.add_parser("subir-directorio", help="sube la entrada firmada del gateway")
    s.add_argument("--llave", required=True)
    s.add_argument("--nombre", default="gateway")
    sub.add_parser("directorio", help="lista el directorio publico")
    s = sub.add_parser("buzon", help="buzon muerto")
    sb = s.add_subparsers(dest="accion", required=True)
    sb.add_parser("secreto")
    d = sb.add_parser("depositar")
    d.add_argument("secreto")
    d.add_argument("texto")
    d.add_argument("--ttl", type=int)
    r = sb.add_parser("retirar")
    r.add_argument("secreto")
    args = p.parse_args(argv)

    try:
        if args.cmd == "llave":
            print(_identidad(args.llave).llave_firma.hex())
        elif args.cmd == "publicar":
            cliente = edge.ClienteEdge(args.url, _identidad(args.llave))
            print("publicado:", cliente.publicar(args.tema, args.texto, args.alias))
        elif args.cmd == "subir-directorio":
            ident = _identidad(args.llave)
            entrada = Entrada.publicar(ident, args.nombre, ROL_RELE | ROL_GATEWAY)
            print(edge.ClienteEdge(args.url, ident).subir_directorio([entrada.a_bytes()]))
        elif args.cmd == "directorio":
            for e in edge.ClienteEdge(args.url, Identidad.nueva()).directorio():
                print(f"{e['id']}  {e['nombre'] or '-':16} {'+'.join(e['roles'])}")
        elif args.accion == "secreto":
            print(os.urandom(32).hex())
        elif args.accion == "depositar":
            edge.depositar(args.url, _secreto(args.secreto), args.texto.encode(), args.ttl)
            print("depositado")
        else:
            texto = edge.retirar(args.url, _secreto(args.secreto))
            print(texto.decode(errors="replace") if texto is not None else "(buzon vacio)")
    except edge.ErrorEdge as e:
        print(f"error del Worker: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
