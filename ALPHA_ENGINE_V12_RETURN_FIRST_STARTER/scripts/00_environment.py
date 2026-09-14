from __future__ import annotations
import json, platform, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs"
OUT.mkdir(exist_ok=True)

info = {
    "python": sys.version,
    "platform": platform.platform(),
    "root": str(ROOT),
    "data_exists": (ROOT / "data").exists(),
    "inputs_exists": (ROOT / "inputs").exists(),
}
(OUT / "environment.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
print(json.dumps(info, indent=2))
if not info["data_exists"]:
    raise SystemExit("ERROR: falta la carpeta data dentro de V12. Copiala y volve a correr.")
