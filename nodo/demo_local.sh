#!/usr/bin/env bash
# Levanta 5 reles FaroNet en linea (n1 - n2 - n3 - n4 - n5) en esta maquina.
# Despues, en otra terminal:
#   python -m faronet --llave /tmp/faronet-demo/yo.key --nombre yo --alias anon --vecino 127.0.0.1:9101
#   > enviar n5 hola
# y para leer el buzon de n5 hay que usar la consola de n5 (DEMO_CONSOLA=5 ./demo_local.sh).
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"
DIR="${DEMO_DIR:-/tmp/faronet-demo}"
mkdir -p "$DIR"
trap 'kill $(jobs -p) 2>/dev/null' EXIT

for i in 1 2 3 4 5; do
    args=(--llave "$DIR/n$i.key" --nombre "n$i" --escuchar "127.0.0.1:910$i" --intervalo-rutas 2)
    [ "$i" -gt 1 ] && args+=(--vecino "127.0.0.1:910$((i - 1))")
    if [ "${DEMO_CONSOLA:-}" = "$i" ]; then
        sleep 1
        "$PY" -m faronet "${args[@]}"
        exit
    fi
    "$PY" -m faronet "${args[@]}" --sin-consola > "$DIR/n$i.log" 2>&1 &
    sleep 0.5
done
echo "5 reles corriendo (logs en $DIR). Ctrl+C para terminar."
wait
