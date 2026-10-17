"""Nodo de FaroNet: rele de circuitos onion y cliente de mensajeria.

Capas dentro de un nodo:

    aplicacion   enviar_mensaje() / buzon
    onion        circuitos: CREAR / CREADA / RELE_IDA / RELE_VUELTA / DESTRUIR
    ruteo (L3)   celdas con DESTINO/ORIGEN de nodo, vector de distancias
    enlaces (L2) TCP, Faro, memoria; HOLA para conocer al vecino

Que sabe cada rele de un circuito: solo el nodo anterior y el siguiente
(`Tramo`). El primero sabe quien es el cliente pero no el destino; la salida
sabe el destino pero no el cliente; el del medio no sabe ninguno de los dos.
"""
from __future__ import annotations

import os
import queue
import random
import struct
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from . import celda as C
from . import onion as O
from .celda import Celda, ErrorCelda, ID_LEN, SIN_ID
from .cripto import CapaOnion, ErrorCripto, HandshakeCliente, Identidad, handshake_rele
from .directorio import ROL_RELE, Directorio, Entrada, VIGENCIA
from .enlaces import Enlace
from .mensaje import Buzon, ErrorMensaje, Mensaje
from .ruteo import TablaRutas, codificar_anuncios, decodificar_anuncios

INACTIVIDAD_TRAMO = 10 * 60  # un circuito sin trafico se olvida a los 10 min


class ErrorNodo(RuntimeError):
    pass


@dataclass
class Tramo:
    """Estado de un circuito en un rele: solo el salto anterior y el siguiente."""
    anterior: bytes
    circ_anterior: int
    capa: CapaOnion
    posicion: int
    siguiente: Optional[bytes] = None
    circ_siguiente: Optional[int] = None
    extendido: bool = False
    usado: float = field(default_factory=time.monotonic)


@dataclass
class Circuito:
    """Estado de un circuito propio (lado cliente)."""
    id: int
    saltos: list[Entrada]
    capas: list[CapaOnion] = field(default_factory=list)
    respuestas: "queue.Queue[tuple[int, int, bytes] | None]" = field(default_factory=queue.Queue)
    creado: float = field(default_factory=time.monotonic)

    @property
    def primero(self) -> bytes:
        return self.saltos[0].id


class Nodo:
    def __init__(self, identidad: Identidad, nombre: str = "", roles: int = ROL_RELE,
                 intervalo_rutas: float = 10.0, saltos: int = O.MIN_SALTOS,
                 timeout: float = 10.0):
        if not O.MIN_SALTOS <= saltos <= O.MAX_SALTOS:
            raise ValueError(f"los circuitos deben tener entre {O.MIN_SALTOS} y {O.MAX_SALTOS} saltos")
        self.identidad = identidad
        self.id = identidad.id
        self.nombre = nombre
        self.roles = roles
        self.saltos = saltos
        self.timeout = timeout
        self.intervalo_rutas = intervalo_rutas
        self.rutas = TablaRutas(self.id, expiracion=3 * intervalo_rutas)
        self.directorio = Directorio()
        self.buzon = Buzon()
        self.enlaces: list[Enlace] = []
        self.al_mensaje: list[Callable[[Mensaje], None]] = []
        self._lock = threading.RLock()
        self._por_anterior: dict[tuple[bytes, int], Tramo] = {}
        self._por_siguiente: dict[tuple[bytes, int], Tramo] = {}
        self._circuitos: dict[tuple[bytes, int], Circuito] = {}
        self._entrada: Optional[Entrada] = None
        self._activo = False

    # ------------------------------------------------------------------ #
    # Ciclo de vida
    # ------------------------------------------------------------------ #
    def iniciar(self) -> "Nodo":
        self._activo = True
        self._publicar()
        threading.Thread(target=self._mantenimiento, name="nodo-mantenimiento", daemon=True).start()
        return self

    def detener(self) -> None:
        self._activo = False
        for enlace in list(self.enlaces):
            enlace.cerrar()

    def panico(self) -> None:
        """Borra llaves y todo el estado sensible (boton de panico)."""
        self.detener()
        with self._lock:
            for circ in self._circuitos.values():
                circ.respuestas.put(None)
            self._circuitos.clear()
            self._por_anterior.clear()
            self._por_siguiente.clear()
        self.buzon.borrar()
        self.directorio.borrar()
        self.rutas.borrar()
        self.identidad.borrar()

    def _mantenimiento(self) -> None:
        ultima_publicacion = time.monotonic()
        while self._activo:
            time.sleep(self.intervalo_rutas)
            if not self._activo:
                return
            self.rutas.purgar()
            self.directorio.purgar()
            self.buzon.purgar()
            self._olvidar_tramos_inactivos()
            if time.monotonic() - ultima_publicacion > VIGENCIA / 2:
                self._publicar()
                ultima_publicacion = time.monotonic()
            for enlace in list(self.enlaces):
                self._anunciar_rutas(enlace)

    # ------------------------------------------------------------------ #
    # Enlaces (capa 2)
    # ------------------------------------------------------------------ #
    def agregar_enlace(self, enlace: Enlace) -> Enlace:
        enlace.al_recibir = self._celda_recibida
        enlace.al_cerrar = self._enlace_cerrado
        with self._lock:
            self.enlaces.append(enlace)
        enlace.iniciar()
        self._enviar_por(enlace, Celda(C.HOLA, origen=self.id))
        return enlace

    def _enlace_cerrado(self, enlace: Enlace) -> None:
        with self._lock:
            if enlace in self.enlaces:
                self.enlaces.remove(enlace)
        self.rutas.enlace_caido(enlace)

    def _enviar_por(self, enlace: Enlace, celda: Celda) -> None:
        enlace.enviar(celda.a_bytes())

    def _anunciar_rutas(self, enlace: Enlace) -> None:
        for cuerpo in codificar_anuncios(self.rutas.anuncio_para(enlace)):
            self._enviar_por(enlace, Celda(C.RUTAS, origen=self.id, cuerpo=cuerpo))

    def _sincronizar_directorio(self, enlace: Enlace) -> None:
        for entrada in self.directorio.entradas():
            self._enviar_por(enlace, Celda(C.DIRECTORIO, origen=self.id, cuerpo=entrada.a_bytes()))

    def _publicar(self) -> None:
        self._entrada = Entrada.publicar(self.identidad, self.nombre, self.roles)
        self.directorio.agregar(self._entrada)
        self._inundar(self._entrada.a_bytes(), excepto=None)

    def _inundar(self, entrada: bytes, excepto: Optional[Enlace]) -> None:
        for enlace in list(self.enlaces):
            if enlace is not excepto:
                self._enviar_por(enlace, Celda(C.DIRECTORIO, origen=self.id, cuerpo=entrada))

    # ------------------------------------------------------------------ #
    # Recepcion y ruteo (capa 3)
    # ------------------------------------------------------------------ #
    def _celda_recibida(self, enlace: Enlace, crudo: bytes) -> None:
        try:
            celda = Celda.desde_bytes(crudo)
        except ErrorCelda:
            return
        try:
            if celda.comando in C.DE_ENLACE:
                self._celda_de_enlace(enlace, celda)
            elif celda.destino == self.id:
                self._celda_para_mi(celda)
            else:
                self._reenviar(celda)
        except (ErrorCripto, O.ErrorOnion, ValueError, struct.error):
            # Datos invalidos de otro nodo: se descarta la celda, nunca se cae el nodo.
            if celda.comando in (C.RELE_IDA, C.RELE_VUELTA, C.CREADA):
                self._destruir_por_celda(celda)

    def _celda_de_enlace(self, enlace: Enlace, celda: Celda) -> None:
        if celda.comando == C.HOLA:
            if celda.origen in (SIN_ID, self.id):
                return
            primera_vez = enlace.vecino is None
            enlace.vecino = celda.origen
            self.rutas.vecino(celda.origen, enlace)
            if primera_vez:
                self._enviar_por(enlace, Celda(C.HOLA, origen=self.id))
                self._anunciar_rutas(enlace)
                self._sincronizar_directorio(enlace)
        elif celda.comando == C.RUTAS:
            if enlace.vecino is not None and self.rutas.procesar_anuncio(
                    enlace, decodificar_anuncios(celda.cuerpo)):
                # Actualizacion inmediata: la red converge sin esperar el periodo.
                for otro in list(self.enlaces):
                    if otro is not enlace:
                        self._anunciar_rutas(otro)
        elif celda.comando == C.DIRECTORIO:
            if self.directorio.agregar_bytes(celda.cuerpo) is not None:
                self._inundar(celda.cuerpo, excepto=enlace)

    def enviar_celda(self, celda: Celda) -> bool:
        """Envia una celda ruteada hacia celda.destino. False si no hay ruta."""
        celda.origen = self.id
        if celda.destino == self.id:
            self._celda_para_mi(celda)
            return True
        enlace = self.rutas.siguiente(celda.destino)
        if enlace is None:
            return False
        self._enviar_por(enlace, celda)
        return True

    def _reenviar(self, celda: Celda) -> None:
        celda.ttl -= 1
        if celda.ttl <= 0:
            return
        enlace = self.rutas.siguiente(celda.destino)
        if enlace is not None:
            self._enviar_por(enlace, celda)

    def _celda_para_mi(self, celda: Celda) -> None:
        manejadores = {
            C.CREAR: self._crear,
            C.CREADA: self._creada,
            C.RELE_IDA: self._rele_ida,
            C.RELE_VUELTA: self._rele_vuelta,
            C.DESTRUIR: self._destruir,
            C.ENTREGA: self._entrega,
        }
        manejador = manejadores.get(celda.comando)
        if manejador is not None:
            manejador(celda)

    # ------------------------------------------------------------------ #
    # Rele
    # ------------------------------------------------------------------ #
    def _crear(self, celda: Celda) -> None:
        clave = (celda.origen, celda.circuito)
        if len(celda.cuerpo) != 33 or celda.circuito == 0:
            return
        posicion = celda.cuerpo[32]
        if not 1 <= posicion <= O.MAX_SALTOS:
            return
        with self._lock:
            if clave in self._por_anterior:
                return
            respuesta, capa = handshake_rele(self.identidad, celda.cuerpo[:32])
            self._por_anterior[clave] = Tramo(celda.origen, celda.circuito, capa, posicion)
        self.enviar_celda(Celda(C.CREADA, destino=celda.origen, circuito=celda.circuito,
                                cuerpo=respuesta))

    def _rele_ida(self, celda: Celda) -> None:
        with self._lock:
            tramo = self._por_anterior.get((celda.origen, celda.circuito))
            if tramo is None:
                return
            tramo.usado = time.monotonic()
            mensaje, reenviar = O.quitar_capa(tramo.capa, tramo.posicion, celda.cuerpo)
        if mensaje is not None:
            self._mensaje_de_rele(tramo, *mensaje)
        elif tramo.extendido:
            self.enviar_celda(Celda(C.RELE_IDA, destino=tramo.siguiente,
                                    circuito=tramo.circ_siguiente, cuerpo=reenviar))
        else:
            raise O.ErrorOnion("celda para un salto que no existe")

    def _rele_vuelta(self, celda: Celda) -> None:
        clave = (celda.origen, celda.circuito)
        with self._lock:
            circuito = self._circuitos.get(clave)
            tramo = self._por_siguiente.get(clave)
            if circuito is not None:
                circuito.respuestas.put(O.desenvolver(circuito.capas, celda.cuerpo))
                return
            if tramo is None or not tramo.extendido:
                return
            tramo.usado = time.monotonic()
            cuerpo = O.agregar_capa(tramo.capa, tramo.posicion, celda.cuerpo)
        self.enviar_celda(Celda(C.RELE_VUELTA, destino=tramo.anterior,
                                circuito=tramo.circ_anterior, cuerpo=cuerpo))

    def _responder(self, tramo: Tramo, comando: int, datos: bytes) -> None:
        with self._lock:
            cuerpo = O.originar(tramo.capa, tramo.posicion, comando, datos)
        self.enviar_celda(Celda(C.RELE_VUELTA, destino=tramo.anterior,
                                circuito=tramo.circ_anterior, cuerpo=cuerpo))

    def _mensaje_de_rele(self, tramo: Tramo, comando: int, datos: bytes) -> None:
        if comando == O.EXTENDER:
            if tramo.siguiente is not None or len(datos) != ID_LEN + 33:
                raise O.ErrorOnion("EXTENDER invalido")
            siguiente = datos[:ID_LEN]
            circ = _id_circuito()
            with self._lock:
                tramo.siguiente, tramo.circ_siguiente = siguiente, circ
                self._por_siguiente[(siguiente, circ)] = tramo
            if not self.enviar_celda(Celda(C.CREAR, destino=siguiente, circuito=circ,
                                           cuerpo=datos[ID_LEN:])):
                self._responder(tramo, O.ERROR, bytes([O.ENTREGA_SIN_RUTA]))
        elif comando == O.ENTREGAR:
            if len(datos) != ID_LEN + O.SOBRE:
                raise O.ErrorOnion("ENTREGAR invalido")
            ok = self.enviar_celda(Celda(C.ENTREGA, destino=datos[:ID_LEN], cuerpo=datos[ID_LEN:]))
            self._responder(tramo, O.ENTREGADO,
                            bytes([O.ENTREGA_OK if ok else O.ENTREGA_SIN_RUTA]))

    def _creada(self, celda: Celda) -> None:
        clave = (celda.origen, celda.circuito)
        with self._lock:
            circuito = self._circuitos.get(clave)
            tramo = self._por_siguiente.get(clave)
        if circuito is not None:
            circuito.respuestas.put((0, C.CREADA, celda.cuerpo))
        elif tramo is not None and not tramo.extendido:
            tramo.extendido = True
            self._responder(tramo, O.EXTENDIDO, celda.cuerpo)

    def _destruir(self, celda: Celda) -> None:
        clave = (celda.origen, celda.circuito)
        with self._lock:
            circuito = self._circuitos.pop(clave, None)
            if circuito is not None:
                circuito.respuestas.put(None)
                return
            tramo = self._por_anterior.get(clave) or self._por_siguiente.get(clave)
        if tramo is not None:
            self._olvidar_tramo(tramo, avisar=True)

    def _destruir_por_celda(self, celda: Celda) -> None:
        with self._lock:
            tramo = (self._por_anterior.get((celda.origen, celda.circuito)) or
                     self._por_siguiente.get((celda.origen, celda.circuito)))
            circuito = self._circuitos.get((celda.origen, celda.circuito))
        if tramo is not None:
            self._olvidar_tramo(tramo, avisar=True)
        if circuito is not None:
            self.cerrar_circuito(circuito)

    def _olvidar_tramo(self, tramo: Tramo, avisar: bool) -> None:
        with self._lock:
            self._por_anterior.pop((tramo.anterior, tramo.circ_anterior), None)
            if tramo.siguiente is not None:
                self._por_siguiente.pop((tramo.siguiente, tramo.circ_siguiente), None)
        if avisar:
            self.enviar_celda(Celda(C.DESTRUIR, destino=tramo.anterior, circuito=tramo.circ_anterior))
            if tramo.siguiente is not None:
                self.enviar_celda(Celda(C.DESTRUIR, destino=tramo.siguiente,
                                        circuito=tramo.circ_siguiente))

    def _olvidar_tramos_inactivos(self) -> None:
        limite = time.monotonic() - INACTIVIDAD_TRAMO
        with self._lock:
            viejos = [t for t in self._por_anterior.values() if t.usado < limite]
        for tramo in viejos:
            self._olvidar_tramo(tramo, avisar=False)

    # ------------------------------------------------------------------ #
    # Destino de extremo a extremo
    # ------------------------------------------------------------------ #
    def _entrega(self, celda: Celda) -> None:
        try:
            mensaje = Mensaje.abrir(self.identidad, celda.cuerpo)
        except (ErrorCripto, ErrorMensaje):
            return
        if mensaje.vencido():
            return
        self.buzon.agregar(mensaje)
        for callback in list(self.al_mensaje):
            callback(mensaje)

    # ------------------------------------------------------------------ #
    # Cliente
    # ------------------------------------------------------------------ #
    def elegir_saltos(self, evitar: tuple[bytes, ...] = ()) -> list[Entrada]:
        """Reles al azar del directorio. El primero debe ser alcanzable."""
        candidatos = [e for e in self.directorio.entradas()
                      if e.es(ROL_RELE) and e.id != self.id and e.id not in evitar]
        alcanzables = [e for e in candidatos if self.rutas.siguiente(e.id) is not None]
        if len(candidatos) < self.saltos or not alcanzables:
            raise ErrorNodo(f"se necesitan al menos {self.saltos} reles conocidos y alcanzables "
                            f"(hay {len(candidatos)})")
        primero = random.SystemRandom().choice(alcanzables)
        resto = [e for e in candidatos if e.id != primero.id]
        return [primero] + random.SystemRandom().sample(resto, self.saltos - 1)

    def construir_circuito(self, saltos: list[Entrada] | None = None) -> Circuito:
        saltos = saltos or self.elegir_saltos()
        circuito = Circuito(_id_circuito(), saltos)
        with self._lock:
            self._circuitos[(circuito.primero, circuito.id)] = circuito
        try:
            for posicion, salto in enumerate(saltos, start=1):
                hs = HandshakeCliente(salto.id, salto.llave_onion)
                crear = hs.publica + bytes([posicion])
                if posicion == 1:
                    if not self.enviar_celda(Celda(C.CREAR, destino=salto.id,
                                                   circuito=circuito.id, cuerpo=crear)):
                        raise ErrorNodo("no hay ruta al primer salto")
                    _, comando, respuesta = self._esperar(circuito)
                    esperado = C.CREADA
                else:
                    self._enviar_rele(circuito, O.EXTENDER, salto.id + crear)
                    origen, comando, respuesta = self._esperar(circuito)
                    if origen != posicion - 1:
                        raise ErrorNodo("respuesta de un salto inesperado")
                    esperado = O.EXTENDIDO
                if comando != esperado:
                    raise ErrorNodo(f"no se pudo extender el circuito al salto {posicion}")
                with self._lock:
                    circuito.capas.append(hs.completar(respuesta))
        except (ErrorNodo, ErrorCripto):
            self.cerrar_circuito(circuito)
            raise
        return circuito

    def _enviar_rele(self, circuito: Circuito, comando: int, datos: bytes,
                     posicion: int | None = None) -> None:
        with self._lock:
            capas = circuito.capas[:posicion]
            cuerpo = O.envolver(capas, comando, datos)
        self.enviar_celda(Celda(C.RELE_IDA, destino=circuito.primero, circuito=circuito.id,
                                cuerpo=cuerpo))

    def _esperar(self, circuito: Circuito) -> tuple[int, int, bytes]:
        try:
            r = circuito.respuestas.get(timeout=self.timeout)
        except queue.Empty:
            raise ErrorNodo("el circuito no respondio a tiempo") from None
        if r is None:
            raise ErrorNodo("el circuito fue destruido")
        return r

    def cerrar_circuito(self, circuito: Circuito) -> None:
        with self._lock:
            self._circuitos.pop((circuito.primero, circuito.id), None)
        circuito.respuestas.put(None)  # despierta a quien este esperando
        self.enviar_celda(Celda(C.DESTRUIR, destino=circuito.primero, circuito=circuito.id))

    def enviar_mensaje(self, destino: str | bytes, texto: str, alias: str = "") -> None:
        """Envia `texto` cifrado de extremo a extremo por un circuito nuevo."""
        entrada = self.directorio.buscar(destino)
        if entrada is None:
            raise ErrorNodo(f"destino desconocido en el directorio: {destino!r}")
        sobre = Mensaje(texto, alias).sellar(entrada.llave_onion)
        circuito = self.construir_circuito(self.elegir_saltos(evitar=(entrada.id,)))
        try:
            self._enviar_rele(circuito, O.ENTREGAR, entrada.id + sobre)
            origen, comando, datos = self._esperar(circuito)
            if comando != O.ENTREGADO or origen != len(circuito.saltos):
                raise ErrorNodo("respuesta inesperada de la salida")
            if datos[:1] != bytes([O.ENTREGA_OK]):
                raise ErrorNodo("la salida no tiene ruta hacia el destino")
        finally:
            self.cerrar_circuito(circuito)

    # ------------------------------------------------------------------ #
    # Consultas
    # ------------------------------------------------------------------ #
    def tramos(self) -> list[Tramo]:
        with self._lock:
            return list(self._por_anterior.values())


def _id_circuito() -> int:
    while True:
        i = struct.unpack(">I", os.urandom(4))[0]
        if i:
            return i
