"""Pruebas de la mesh FaroNet.

    cd nodo && python3 -m unittest -v
"""
import threading
import time
import unittest

from faronet import celda as C
from faronet import onion as O
from faronet.celda import CELDA, CUERPO, Celda, ErrorCelda
from faronet.cripto import ErrorCripto, HandshakeCliente, Identidad, handshake_rele
from faronet.directorio import ROL_GATEWAY, ROL_RELE, Directorio, Entrada, ErrorDirectorio
from faronet.enlaces import EnlaceMemoria, EnlaceTCP, ServidorTCP
from faronet.mensaje import (Buzon, ErrorMensaje, Mensaje, MensajePublico, MAX_TEXTO, PUBLICO,
                             PRIVADO, TEMA_PRIVADO)
from faronet.nodo import ErrorNodo, Nodo
from faronet.ruteo import INFINITO, TablaRutas, codificar_anuncios, decodificar_anuncios


def esperar(condicion, timeout=5.0):
    limite = time.monotonic() + timeout
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.02)
    return False


class TestCelda(unittest.TestCase):
    def test_tamano_fijo_e_ida_y_vuelta(self):
        for cuerpo in (b"", b"hola", b"x" * CUERPO):
            c = Celda(C.ENTREGA, b"\x01" * 8, b"\x02" * 8, 7, cuerpo)
            crudo = c.a_bytes()
            self.assertEqual(len(crudo), CELDA)
            self.assertEqual(Celda.desde_bytes(crudo), c)

    def test_rechaza_otra_version_y_largo(self):
        crudo = bytearray(Celda(C.HOLA).a_bytes())
        crudo[0] = 2
        with self.assertRaises(ErrorCelda):
            Celda.desde_bytes(bytes(crudo))
        with self.assertRaises(ErrorCelda):
            Celda.desde_bytes(b"\x01" * 100)


class TestCripto(unittest.TestCase):
    def test_handshake_llaves_iguales(self):
        rele = Identidad.nueva()
        hs = HandshakeCliente(rele.id, rele.llave_onion)
        respuesta, capa_rele = handshake_rele(rele, hs.publica)
        capa_cliente = hs.completar(respuesta)
        ct = capa_cliente.cifrar(1, b"secreto")
        self.assertEqual(capa_rele.descifrar(1, ct), b"secreto")
        self.assertEqual(capa_cliente.descifrar(2, capa_rele.cifrar(2, b"vuelta")), b"vuelta")

    def test_impostor_no_completa_handshake(self):
        rele, impostor = Identidad.nueva(), Identidad.nueva()
        hs = HandshakeCliente(rele.id, rele.llave_onion)
        respuesta, _ = handshake_rele(impostor, hs.publica)
        with self.assertRaises(ErrorCripto):
            hs.completar(respuesta)

    def test_identidad_desde_semilla_es_estable(self):
        a = Identidad.nueva()
        b = Identidad(a.semilla)
        self.assertEqual((a.id, a.llave_onion), (b.id, b.llave_onion))
        a.borrar()
        self.assertEqual(a.semilla, bytes(32))


class TestOnion(unittest.TestCase):
    def _circuito(self, n):
        clientes, reles = [], []
        for _ in range(n):
            ident = Identidad.nueva()
            hs = HandshakeCliente(ident.id, ident.llave_onion)
            resp, capa_rele = handshake_rele(ident, hs.publica)
            clientes.append(hs.completar(resp))
            reles.append(capa_rele)
        return clientes, reles

    def test_ida_llega_al_salto_correcto_con_tamano_constante(self):
        clientes, reles = self._circuito(3)
        for destino in (1, 2, 3):
            cuerpo = O.envolver(clientes[:destino], O.ENTREGAR, b"datos %d" % destino)
            for p in range(1, destino + 1):
                self.assertEqual(len(cuerpo), CUERPO)
                mensaje, cuerpo = O.quitar_capa(reles[p - 1], p, cuerpo)
                if p < destino:
                    self.assertIsNone(mensaje)
            self.assertEqual(mensaje, (O.ENTREGAR, b"datos %d" % destino))

    def test_vuelta_identifica_al_salto_de_origen(self):
        clientes, reles = self._circuito(3)
        cuerpo = O.originar(reles[2], 3, O.ENTREGADO, b"\x00")
        for p in (2, 1):
            cuerpo = O.agregar_capa(reles[p - 1], p, cuerpo)
            self.assertEqual(len(cuerpo), CUERPO)
        self.assertEqual(O.desenvolver(clientes, cuerpo), (3, O.ENTREGADO, b"\x00"))

    def test_celda_alterada_se_detecta(self):
        clientes, reles = self._circuito(3)
        cuerpo = bytearray(O.envolver(clientes, O.ENTREGAR, b"x"))
        cuerpo[100] ^= 1
        with self.assertRaises(ErrorCripto):
            O.quitar_capa(reles[0], 1, bytes(cuerpo))


class TestDirectorio(unittest.TestCase):
    def test_entrada_firmada(self):
        ident = Identidad.nueva()
        e = Entrada.publicar(ident, "faro-norte")
        self.assertEqual(Entrada.desde_bytes(e.a_bytes()), e)

    def test_entrada_alterada_o_vencida(self):
        ident = Identidad.nueva()
        crudo = bytearray(Entrada.publicar(ident, "faro-norte").a_bytes())
        crudo[50] ^= 1
        with self.assertRaises(ErrorDirectorio):
            Entrada.desde_bytes(bytes(crudo))
        vieja = Entrada.publicar(ident, ahora=time.time() - 3600, vigencia=60)
        with self.assertRaises(ErrorDirectorio):
            Entrada.desde_bytes(vieja.a_bytes())

    def test_solo_acepta_entradas_mas_nuevas(self):
        ident = Identidad.nueva()
        d = Directorio()
        nueva = Entrada.publicar(ident, ahora=time.time())
        vieja = Entrada.publicar(ident, ahora=time.time() - 10)
        self.assertTrue(d.agregar(nueva))
        self.assertFalse(d.agregar(vieja))
        self.assertEqual(d.buscar(ident.id.hex()), nueva)


class TestMensaje(unittest.TestCase):
    def test_sobre_de_tamano_fijo(self):
        dest = Identidad.nueva()
        corto = Mensaje("hola", alias="anon").sellar(dest.llave_onion)
        largo = Mensaje("x" * MAX_TEXTO).sellar(dest.llave_onion)
        self.assertEqual(len(corto), O.SOBRE)
        self.assertEqual(len(largo), O.SOBRE)
        self.assertEqual(Mensaje.abrir(dest, corto).texto, "hola")
        with self.assertRaises(ErrorCripto):
            Mensaje.abrir(Identidad.nueva(), corto)

    def test_tema_privado_viaja_dentro_del_sobre(self):
        dest = Identidad.nueva()
        sobre = Mensaje("reunion a las 8", alias="ana", tema="vecinos").sellar(dest.llave_onion)
        self.assertEqual(len(sobre), O.SOBRE)  # mismo tamano que un privado normal
        m = Mensaje.abrir(dest, sobre)
        self.assertEqual((m.tipo, m.tema, m.alias, m.texto),
                         (TEMA_PRIVADO, "vecinos", "ana", "reunion a las 8"))
        self.assertEqual(Mensaje.abrir(dest, Mensaje("sin tema").sellar(dest.llave_onion)).tipo, PRIVADO)
        with self.assertRaises(ErrorMensaje):
            Mensaje("x", tema="Con Espacios").a_bytes()

    def test_buzon_respeta_ttl(self):
        b = Buzon()
        b.agregar(Mensaje("viejo", ttl=1, creado=int(time.time()) - 5))
        b.agregar(Mensaje("nuevo"))
        self.assertEqual([m.texto for m in b.mensajes()], ["nuevo"])


class TestRuteo(unittest.TestCase):
    def test_anuncios_ida_y_vuelta(self):
        anuncios = [(bytes([i]) * 8, i % 17) for i in range(120)]
        cuerpos = codificar_anuncios(anuncios)
        self.assertEqual(len(cuerpos), 3)
        self.assertEqual(sum((decodificar_anuncios(c) for c in cuerpos), []), anuncios)

    def test_mejor_ruta_y_envenenamiento(self):
        a, b, d = b"A" * 8, b"B" * 8, b"D" * 8
        lento, rapido = EnlaceMemoria(costo=4), EnlaceMemoria(costo=1)
        t = TablaRutas(a)
        t.procesar_anuncio(lento, [(d, 0)])
        t.procesar_anuncio(rapido, [(b, 0), (d, 1)])
        self.assertIs(t.siguiente(d), rapido)
        self.assertEqual(t.metrica(d), 2)
        self.assertIn((d, INFINITO), t.anuncio_para(rapido))
        t.procesar_anuncio(rapido, [(d, INFINITO)])
        self.assertIsNone(t.siguiente(d))


def armar_red(n, aristas, roles=None, identidades=None, **kw):
    roles, identidades = roles or {}, identidades or {}
    nodos = [Nodo(identidades.get(i) or Identidad.nueva(), nombre=f"n{i}",
                  roles=roles.get(i, ROL_RELE), intervalo_rutas=0.3, timeout=5, **kw).iniciar()
             for i in range(n)]
    for i, j in aristas:
        a, b = EnlaceMemoria.par()
        nodos[i].agregar_enlace(a)
        nodos[j].agregar_enlace(b)
    return nodos


def convergio(nodos):
    return all(len(n.directorio.entradas()) == len(nodos) and
               all(n.rutas.siguiente(o.id) for o in nodos if o is not n) for n in nodos)


class TestRed(unittest.TestCase):
    def setUp(self):
        # Topologia: dos comunidades unidas solo por el enlace 2-3 ("el Faro")
        #   0 - 1 - 2 ===== 3 - 4 - 5
        #        \_/         \_/
        self.nodos = armar_red(6, [(0, 1), (1, 2), (0, 2), (2, 3), (3, 4), (4, 5), (3, 5)])
        self.assertTrue(esperar(lambda: convergio(self.nodos), 10), "la red no convergio")

    def tearDown(self):
        for n in self.nodos:
            n.detener()

    def test_mensaje_anonimo_de_extremo_a_extremo(self):
        origen, destino = self.nodos[0], self.nodos[5]
        recibidos = []
        destino.al_mensaje.append(recibidos.append)
        origen.enviar_mensaje("n5", "hola desde la otra comunidad", alias="anon")
        self.assertTrue(esperar(lambda: recibidos))
        self.assertEqual(recibidos[0].texto, "hola desde la otra comunidad")
        self.assertEqual(recibidos[0].alias, "anon")

    def test_ningun_rele_conoce_origen_y_destino(self):
        origen, destino = self.nodos[0], self.nodos[5]
        circuito = origen.construir_circuito(origen.elegir_saltos(evitar=(destino.id,)))
        try:
            vistos = {}
            for n in self.nodos:
                for t in n.tramos():
                    vistos[n.id] = {t.anterior, t.siguiente}
            self.assertEqual(len(vistos), 3)
            for conocidos in vistos.values():
                self.assertFalse(origen.id in conocidos and destino.id in conocidos)
            salida = circuito.saltos[-1].id
            self.assertNotIn(origen.id, vistos[salida])
        finally:
            origen.cerrar_circuito(circuito)

    def test_ruta_alterna_si_cae_un_enlace(self):
        n0 = self.nodos[0]
        directo = n0.rutas.siguiente(self.nodos[2].id)
        directo.cerrar()
        self.assertTrue(esperar(lambda: n0.rutas.siguiente(self.nodos[2].id) is not None
                                and n0.rutas.metrica(self.nodos[2].id) == 2))

    def test_tema_privado_llega_a_cada_miembro(self):
        origen = self.nodos[0]
        recibidos = {4: [], 5: []}
        for i, lista in recibidos.items():
            self.nodos[i].al_mensaje.append(lista.append)
        origen.crear_tema_privado("vecinos", ["n4", "n5", "n0"])  # n0 es el propio nodo
        self.assertEqual(origen.enviar_tema("vecinos", "solo para el grupo", alias="ana"), [])
        self.assertTrue(esperar(lambda: recibidos[4] and recibidos[5]))
        for lista in recibidos.values():
            self.assertEqual((lista[0].tema, lista[0].texto, lista[0].alias),
                             ("vecinos", "solo para el grupo", "ana"))
        self.assertEqual(origen.enviar_tema("vecinos", "otro"), [])
        with self.assertRaises(ErrorNodo):
            origen.enviar_tema("desconocido", "x")

    def test_panico_borra_estado(self):
        n = self.nodos[1]
        n.crear_tema_privado("secreto", ["n2"])
        n.panico()
        self.assertEqual(n.temas_privados, {})
        self.assertEqual(n.directorio.entradas(), [])
        self.assertEqual(n.buzon.mensajes(), [])
        self.assertEqual(n.identidad.semilla, bytes(32))


class TestMensajePublico(unittest.TestCase):
    def test_tamano_fijo_y_validacion(self):
        corto = MensajePublico("general", "hola").a_bytes()
        largo = MensajePublico("general", "x" * 300, "anon").a_bytes()
        self.assertEqual((len(corto), len(largo)), (PUBLICO, PUBLICO))
        self.assertEqual(MensajePublico.desde_bytes(largo).texto, "x" * 300)
        for malo in (MensajePublico("Mayus", "x"), MensajePublico("general", "  "),
                     MensajePublico("general", "x" * 501)):
            with self.assertRaises(ErrorMensaje):
                malo.a_bytes()


class TestPublicar(unittest.TestCase):
    def setUp(self):
        #   0 - 1 - 2 - 3 - 4(gateway)
        self.nodos = armar_red(5, [(0, 1), (1, 2), (2, 3), (3, 4)], roles={4: ROL_RELE | ROL_GATEWAY})
        self.assertTrue(esperar(lambda: convergio(self.nodos), 10))
        self.gateway = self.nodos[4]
        self.publicados = []

        def subir(m):
            self.publicados.append(m)
            return True
        self.gateway.al_publicar = subir

    def tearDown(self):
        for n in self.nodos:
            n.detener()

    def test_mensaje_publico_llega_al_gateway_sin_origen(self):
        vistos = []
        original = self.gateway._mensaje_de_rele

        def espiar(tramo, comando, datos):
            vistos.append(tramo.anterior)
            original(tramo, comando, datos)
        self.gateway._mensaje_de_rele = espiar
        self.nodos[0].publicar("general", "hola clearnet", alias="anon")
        self.assertEqual([(m.tema, m.texto, m.alias) for m in self.publicados],
                         [("general", "hola clearnet", "anon")])
        self.assertNotIn(self.nodos[0].id, vistos)  # el gateway no ve al origen

    def test_tema_privado_no_sale_a_clearnet(self):
        self.nodos[0].crear_tema_privado("vecinos", ["n1"])
        with self.assertRaises(ErrorNodo):
            self.nodos[0].publicar("vecinos", "esto no debe salir")
        self.assertEqual(self.publicados, [])

    def test_gateway_sin_edge(self):
        self.gateway.al_publicar = None
        with self.assertRaises(ErrorNodo):
            self.nodos[0].publicar("general", "no hay edge")

    def test_edge_rechaza(self):
        self.gateway.al_publicar = lambda m: False
        with self.assertRaises(ErrorNodo):
            self.nodos[0].publicar("general", "rechazado")


class TestTCP(unittest.TestCase):
    def test_red_por_tcp(self):
        nodos = [Nodo(Identidad.nueva(), nombre=f"t{i}", intervalo_rutas=0.3, timeout=5).iniciar()
                 for i in range(5)]
        servidores = []
        try:
            for i in range(1, 5):
                servidores.append(ServidorTCP("127.0.0.1", 0, nodos[i].agregar_enlace))
            for i in range(1, 5):  # estrella alrededor de t0 + linea t1-t2-t3-t4
                nodos[0].agregar_enlace(EnlaceTCP.conectar("127.0.0.1", servidores[i - 1].puerto))
            for i in range(1, 4):
                nodos[i].agregar_enlace(EnlaceTCP.conectar("127.0.0.1", servidores[i].puerto))
            self.assertTrue(esperar(lambda: convergio(nodos), 10))
            recibidos = []
            nodos[4].al_mensaje.append(recibidos.append)
            nodos[0].enviar_mensaje("t4", "por tcp")
            self.assertTrue(esperar(lambda: recibidos))
        finally:
            for n in nodos:
                n.detener()
            for s in servidores:
                s.cerrar()


class TestFaroSimulado(unittest.TestCase):
    def test_celdas_cruzan_la_luz(self):
        try:
            from dispositivo_luz_adaptador import DispositivoLuzAdaptador
            from dispositivo_luz_adaptador.simulador import FaroSimulado, MedioSimulado
        except ImportError:
            self.skipTest("falta dispositivo_luz_adaptador")
        from faronet.enlaces import EnlaceFaro

        medio = MedioSimulado(ber=1e-5, semilla=7)
        faro_a = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
        faro_b = DispositivoLuzAdaptador(FaroSimulado(medio)).abrir()
        # 0 - 1 ~~luz~~ 2 - 3
        #                 \_ 4
        nodos = armar_red(5, [(0, 1), (2, 3), (2, 4)])
        try:
            nodos[1].agregar_enlace(EnlaceFaro(faro_a))
            nodos[2].agregar_enlace(EnlaceFaro(faro_b))
            self.assertTrue(esperar(lambda: convergio(nodos), 15))
            recibidos = []
            nodos[3].al_mensaje.append(recibidos.append)
            nodos[0].enviar_mensaje("n3", "cruzando la luz")
            self.assertTrue(esperar(lambda: recibidos, 10))
        finally:
            for n in nodos:
                n.detener()
            faro_a.cerrar()
            faro_b.cerrar()


if __name__ == "__main__":
    unittest.main()
