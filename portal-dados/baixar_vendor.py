"""Baixa (na hora do build) as bibliotecas do Gêmeo 3D, para a página não depender de CDN.
Versões fixas: three.js 0.160.0 e web-ifc 0.0.57."""
import sys
import urllib.request
from pathlib import Path

CDN = "https://cdn.jsdelivr.net/npm/"
ARQUIVOS = {
    "three.module.js": "three@0.160.0/build/three.module.js",
    "OrbitControls.js": "three@0.160.0/examples/jsm/controls/OrbitControls.js",
    "web-ifc-api.js": "web-ifc@0.0.57/web-ifc-api.js",
    "web-ifc.wasm": "web-ifc@0.0.57/web-ifc.wasm",
}
destino = Path(sys.argv[1])
destino.mkdir(parents=True, exist_ok=True)
for nome, caminho in ARQUIVOS.items():
    dados = urllib.request.urlopen(CDN + caminho, timeout=120).read()
    if len(dados) < 1000:
        sys.exit(f"download estranho: {nome} ({len(dados)} bytes)")
    (destino / nome).write_bytes(dados)
    print(f"{nome}: {len(dados) / 1e6:.2f} MB")
