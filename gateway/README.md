# gateway

Puente entre FaroNet y el edge (Raspberry Pi). Por ahora contiene el cliente
firmado del Worker (`faronet_gateway/edge.py`) y su CLI `faronet-edge`.

```bash
pip install -e adaptador -e nodo -e gateway      # desde la raíz, en el venv

faronet-edge llave --llave ~/llaves/gateway.key  # llave pública para GATEWAYS
faronet-edge --url https://faronet.<cuenta>.workers.dev publicar --llave ~/llaves/gateway.key general "hola"
faronet-edge --url URL subir-directorio --llave ~/llaves/gateway.key
faronet-edge --url URL directorio

S=$(faronet-edge buzon secreto)                  # secreto compartido (32 bytes hex)
faronet-edge --url URL buzon depositar "$S" "nos vemos en el faro norte"
faronet-edge --url URL buzon retirar "$S"
```

El gateway firma con la misma identidad Ed25519 del nodo FaroNet (la semilla de
`--llave`, o la guardada en el Faro). El buzón muerto no lleva firma: lo usa
quien tenga el secreto.

Pruebas: `cd gateway && python -m unittest -v` (levanta `wrangler dev` si está
instalado `worker/node_modules`).

## Pendiente

* Comando de relé `PUBLICAR` en la mesh: la salida del circuito entrega el
  mensaje público al gateway, y el gateway lo sube con `ClienteEdge.publicar`.
* Subir el directorio de la mesh al Worker periódicamente.
