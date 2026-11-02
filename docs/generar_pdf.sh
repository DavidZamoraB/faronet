#!/usr/bin/env bash
# Genera docs/documentacion.pdf: documentacion.md + el RFC (rfc-faronet.txt) como anexo.
# Requiere pandoc y Chromium (o Google Chrome).   Uso: ./docs/generar_pdf.sh
set -euo pipefail
cd "$(dirname "$0")"
CHROME=${CHROME:-$(command -v chromium || command -v chromium-browser || command -v google-chrome)}
tmp=$(mktemp -d)
pandoc documentacion.md -s --toc --toc-depth=2 --css estilo.css --embed-resources \
       --metadata toc-title="Contenido" -o "$tmp/doc.html"
python3 - "$tmp/doc.html" rfc-faronet.txt <<'PY'
import html, sys
doc, rfc = sys.argv[1], sys.argv[2]
paginas = open(rfc, encoding="utf-8").read().split("\f")  # si el RFC viene paginado
anexo = "".join(f'<pre class="rfc">{html.escape(p.strip(chr(10)))}</pre>' for p in paginas if p.strip())
s = open(doc, encoding="utf-8").read().replace("</body>", anexo + "</body>")
open(doc, "w", encoding="utf-8").write(s)
PY
"$CHROME" --headless --no-sandbox --disable-gpu --no-pdf-header-footer \
          --print-to-pdf="$PWD/documentacion.pdf" "file://$tmp/doc.html" 2>/dev/null
rm -rf "$tmp"
echo "listo: docs/documentacion.pdf"
