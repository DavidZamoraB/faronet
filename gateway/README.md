# gateway

Puente entre FaroNet y el edge (Raspberry Pi):

* `faronet_gateway/puente.py`: se engancha al nodo gateway. Sube al Worker los
  mensajes públicos que llegan por la mesh (comando de relé `PUBLICAR`) y, cada
  5 minutos, el directorio de nodos. Se activa con `faronet --gateway --edge URL`.
* `faronet_gateway/edge.py`: cliente firmado del Worker y buzón muerto cifrado,
  con su CLI `faronet-edge`.

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

Cadena completa: `nodo --circuito onion--> gateway --HTTPS firmado--> Worker --WebSocket--> navegador`.
