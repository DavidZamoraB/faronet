# FaroNet

Proyecto 1 — Redes de Computadoras, Tecnológico de Costa Rica (Prof. Kevin Moraga).

Red de comunicación por luz con una mesh anónima y una aplicación pública en el edge.

**Integrantes:** David Zamora, Diego Zamora

## Estructura

| Carpeta | Contenido |
| --- | --- |
| `firmware/` | Código Arduino del Faro |
| `adaptador/` | Biblioteca DispositivoLuzAdaptador |
| `nodo/` | Nodos de la mesh y cliente de terminal |
| `gateway/` | Puente FaroNet <-> edge (Raspberry Pi) |
| `worker/` | Cloudflare Worker + `wrangler.toml` |
| `hardware/` | Esquemático, BOM, fotos y bitácora de pruebas |
| `docs/` | Documentación y RFC |

## Flujo de trabajo

- `main` siempre estable y compilable.
- Una rama por funcionalidad (`feature/<tema>`), integrada por pull request revisado por el otro integrante.
- No se suben secretos ni llaves; los del Worker se cargan con `wrangler secret`.

## Integración continua

Cada pull request corre `.github/workflows/ci.yml`: las pruebas de `adaptador/`
(incluidas las del núcleo del firmware en C++), las de la mesh en `nodo/` y la
compilación del firmware para Arduino Nano y Uno.
