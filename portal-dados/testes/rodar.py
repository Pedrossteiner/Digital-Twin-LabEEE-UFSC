import sys
import time
import zipfile
import io
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import exportar as ex  # noqa: E402
from simulado import FonteSimulada  # noqa: E402

saida = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
tz = ZoneInfo("America/Sao_Paulo")
ini = datetime(2026, 11, 3, tzinfo=tz)
fim = datetime(2026, 11, 10, tzinfo=tz)
fonte = FonteSimulada(ini, fim)
for res in ("10min", "1h", "bruto"):
    for fuso in ("local", "utc"):
        for fmt in ("xlsx", "csv"):
            t = time.time()
            nome, dados = ex.pacote(fonte, ini, fim, ["ambiente", "presenca", "janelas", "ar"], res, fuso, fmt)
            (saida / nome).write_bytes(dados)
            z = zipfile.ZipFile(io.BytesIO(dados))
            print(f"{nome}: {len(dados)/1e6:.2f} MB em {time.time()-t:.1f}s -> {z.namelist()}")
