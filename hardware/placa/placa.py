"""Distribucion del Faro (version Arduino Uno) en la placa perforada HS-03 de
pads individuales. Coordenadas = columna (letra) + fila (numero) impresas en
la placa, vistas desde el lado de los componentes.

    python hardware/placa/placa.py            # verifica conexiones y cortos
    python hardware/placa/placa.py --lista    # lista de uniones a soldar
"""
import collections
import string
import sys

L = string.ascii_uppercase


def p(s):
    return s[0], int(s[1:])


# componente -> {pata: pad}
# Nota: la primera cadena del LED rojo (H14-H20) quedo en corto con el riel al
# soldar; se reubico en H22-H28. Lo que quedo en H14-H19 no se conecta a nada.
COMP = {
    "J1 conector 9 pines": {"5V": "B6", "GND": "B7", "D2": "B8", "A0": "B9", "D4": "B10",
                            "D3": "B11", "D5": "B12", "D6": "B13", "D7": "B14"},
    "C2 100uF": {"+": "D6", "-": "D7"},
    "R1 100 (diseño: 82)": {"a": "R4", "b": "V4"},
    "LED1 IR": {"anodo": "W4", "catodo": "W5"},
    "Q1 2N2222": {"C": "U6", "B": "U7", "E": "U8"},
    "R2 1k": {"a": "P7", "b": "T7"},
    "R5 10k": {"a": "K4", "b": "K8"},
    "R9 10k": {"a": "H3", "b": "H7"},
    "R10 1k": {"a": "H8", "b": "H12"},
    "R4 1.5M": {"a": "K10", "b": "K13"},
    "U1 LM393": {"1": "M10", "2": "M11", "3": "M12", "4": "M13",
                 "8": "P10", "7": "P11", "6": "P12", "5": "P13"},
    "C1 10nF (10nJ; diseño: 100nF)": {"a": "Q11", "b": "Q13"},
    "Q2 sensor": {"corta": "W12", "larga": "W13"},
    "R3 10k": {"a": "S14", "b": "S18"},
    "R6 330": {"a": "D22", "b": "D26"}, "LED2 (reemplazo)": {"anodo": "D27", "catodo": "D28"},
    "R7 330": {"a": "F14", "b": "F18"}, "LED3 azul": {"anodo": "F19", "catodo": "F20"},
    "R8 330": {"a": "H22", "b": "H26"}, "LED4 rojo": {"anodo": "H27", "catodo": "H28"},
    "SW1 boton": {"a": "I15", "b": "M15", "c": "I17", "d": "M17"},
}
RIEL_5V = [f"{c}2" for c in L[2:22]]     # C2..V2
RIEL_GND = [f"{c}20" for c in L[2:21]]   # C20..U20

# red -> puentes (pads vecinos unidos por detras) y cables (de pad a pad)
NETS = {
    "5V": {"puentes": [("B6", "C6"), ("C6", "D6"), ("C6", "C5"), ("C5", "C4"), ("C4", "C3"), ("C3", "C2"),
                       ("R4", "R3"), ("R3", "R2"), ("K4", "K3"), ("K3", "K2"), ("H3", "H2"),
                       ("P10", "Q10"), ("Q10", "Q11"), ("Q11", "Q12"), ("Q12", "P12"),
                       ("Q10", "Q9"), ("Q9", "Q8"), ("Q8", "Q7"), ("Q7", "Q6"), ("Q6", "Q5"), ("Q5", "Q4"),
                       ("Q4", "Q3"), ("Q3", "Q2")],
           "cables": [("W12", "V2")], "riel": RIEL_5V},
    "GND": {"puentes": [("B7", "C7"), ("C7", "D7"), ("M13", "N13"), ("N13", "O13"), ("O13", "P13"),
                        ("P13", "Q13"), ("S18", "S19"), ("S19", "S20"),
                        ("M17", "M18"), ("M18", "M19"), ("M19", "M20"),
                        ("N13", "N14"), ("N14", "N15"), ("N15", "N16"), ("N16", "N17"), ("N17", "N18"),
                        ("N18", "N19"), ("N19", "N20"),
                        ("H28", "G28"), ("G28", "F28"), ("F28", "E28"), ("E28", "D28"), ("D28", "C28"),
                        ("C28", "C27"), ("C27", "C26"), ("C26", "C25"), ("C25", "C24"), ("C24", "C23"),
                        ("C23", "C22"), ("C22", "C21"), ("C21", "C20")],
            "cables": [("C7", "C20"), ("U8", "U20"), ("H12", "G20")], "riel": RIEL_GND},
    "ANODO_IR": {"puentes": [("V4", "W4")], "cables": []},
    "COLECTOR": {"puentes": [("W5", "W6"), ("W6", "V6"), ("V6", "U6")], "cables": []},
    "BASE": {"puentes": [("T7", "U7")], "cables": []},
    "D4": {"puentes": [], "cables": [("B10", "P7")]},
    "SALIDA/D2": {"puentes": [("M10", "M9"), ("M9", "L9"), ("L9", "K9"), ("K9", "K8"), ("K9", "K10")],
                  "cables": [("B8", "L9")]},
    "SENSOR/A0": {"puentes": [("W13", "V13"), ("V13", "U13"), ("U13", "T13"), ("T13", "S13"), ("S13", "S14"),
                              ("M12", "L12"), ("L12", "L13"), ("L13", "K13"), ("K13", "J13")],
                  "cables": [("T13", "J13"), ("B9", "U13")]},
    "UMBRAL": {"puentes": [("H7", "H8")], "cables": [("H8", "M11")]},
    "D5": {"puentes": [], "cables": [("B12", "D22")]},
    "D6": {"puentes": [], "cables": [("B13", "F14")]},
    "D7": {"puentes": [], "cables": [("B14", "H22")]},
    "D5_LED": {"puentes": [("D26", "D27")], "cables": []},
    "D6_LED": {"puentes": [("F18", "F19")], "cables": []},
    "D7_LED": {"puentes": [("H26", "H27")], "cables": []},
    "D3": {"puentes": [], "cables": [("B11", "I15")]},
}
PIN_RED = {
    "J1 conector 9 pines": {"5V": "5V", "GND": "GND", "D2": "SALIDA/D2", "A0": "SENSOR/A0", "D4": "D4",
                            "D3": "D3", "D5": "D5", "D6": "D6", "D7": "D7"},
    "C2 100uF": {"+": "5V", "-": "GND"}, "R1 100 (diseño: 82)": {"a": "5V", "b": "ANODO_IR"},
    "LED1 IR": {"anodo": "ANODO_IR", "catodo": "COLECTOR"},
    "Q1 2N2222": {"C": "COLECTOR", "B": "BASE", "E": "GND"}, "R2 1k": {"a": "D4", "b": "BASE"},
    "R5 10k": {"a": "5V", "b": "SALIDA/D2"}, "R9 10k": {"a": "5V", "b": "UMBRAL"},
    "R10 1k": {"a": "UMBRAL", "b": "GND"}, "R4 1.5M": {"a": "SALIDA/D2", "b": "SENSOR/A0"},
    "U1 LM393": {"1": "SALIDA/D2", "2": "UMBRAL", "3": "SENSOR/A0", "4": "GND",
                 "8": "5V", "7": None, "6": "5V", "5": "GND"},
    "C1 10nF (10nJ; diseño: 100nF)": {"a": "5V", "b": "GND"}, "Q2 sensor": {"corta": "5V", "larga": "SENSOR/A0"},
    "R3 10k": {"a": "SENSOR/A0", "b": "GND"},
    "R6 330": {"a": "D5", "b": "D5_LED"}, "LED2 (reemplazo)": {"anodo": "D5_LED", "catodo": "GND"},
    "R7 330": {"a": "D6", "b": "D6_LED"}, "LED3 azul": {"anodo": "D6_LED", "catodo": "GND"},
    "R8 330": {"a": "D7", "b": "D7_LED"}, "LED4 rojo": {"anodo": "D7_LED", "catodo": "GND"},
    "SW1 boton": {"a": "D3", "b": None, "c": None, "d": "GND"},
}


def verificar() -> int:
    padre = {}

    def f(x):
        padre.setdefault(x, x)
        while padre[x] != x:
            padre[x] = padre[padre[x]]
            x = padre[x]
        return x

    def u(a, b):
        padre[f(a)] = f(b)

    errores = 0
    for red, d in NETS.items():
        for a, b in d["puentes"]:
            (ca, ra), (cb, rb) = p(a), p(b)
            if abs(L.index(ca) - L.index(cb)) + abs(ra - rb) != 1:
                print("puente no vecino:", a, b); errores += 1
            u(a, b)
        for a, b in d["cables"]:
            u(a, b)
        r = d.get("riel", [])
        for a, b in zip(r, r[1:]):
            u(a, b)
    usados = {}
    for c, pins in COMP.items():
        for pad in pins.values():
            if pad in usados:
                print("pad repetido:", pad, c, usados[pad]); errores += 1
            usados[pad] = c
    grupos = collections.defaultdict(set)
    for c, pins in COMP.items():
        for pin, pad in pins.items():
            if PIN_RED[c][pin]:
                grupos[PIN_RED[c][pin]].add(f(pad))
    raiz = {}
    for red, rs in grupos.items():
        if len(rs) != 1:
            print("red partida:", red); errores += 1
        for r in rs:
            if r in raiz and raiz[r] != red:
                print("CORTO:", red, raiz[r]); errores += 1
            raiz[r] = red
    for c, pins in COMP.items():
        for pin, pad in pins.items():
            if PIN_RED[c][pin] is None and f(pad) in raiz:
                print("pata libre conectada:", c, pin); errores += 1
    print(f"redes: {len(grupos)} | componentes: {len(COMP)} | errores: {errores}")
    return errores


if __name__ == "__main__":
    sys.exit(1 if verificar() else 0)
