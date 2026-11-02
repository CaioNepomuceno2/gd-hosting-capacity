"""Extrai trafos e alimentadores de cada snapshot da BDGD (um por vez, apagando o .gdb para poupar disco).

Uso: ``python scripts/02_build_bdgd.py [anos...]``. Se ``GDHC_GDB_<ANO>`` apontar para um .gdb já extraído,
ele é usado e não é apagado.
"""
import logging
import os
import shutil
import sys
from pathlib import Path

import pandas as pd

from gdhc import bdgd
from gdhc.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
cfg = Config.load()
registro = pd.read_parquet(cfg.interim / "registro_gd.parquet").drop_duplicates("ceg").set_index("ceg").kw
anos = [int(a) for a in sys.argv[1:]] or sorted(cfg.bdgd_snapshots, reverse=True)
for ano in anos:
    out_t, out_a = cfg.interim / f"trafos_{ano}.parquet", cfg.interim / f"alimentadores_{ano}.parquet"
    if out_t.exists() and out_a.exists():
        continue
    externo = os.environ.get(f"GDHC_GDB_{ano}")
    dest = cfg.raw / "bdgd" / str(ano)
    gdb = Path(externo) if externo else bdgd.download(cfg.bdgd_snapshots[ano], dest)
    if not out_t.exists():
        bdgd.trafos(gdb, ano, registro).to_parquet(out_t, index=False)
    if not out_a.exists():
        bdgd.alimentadores(gdb, ano, registro).to_parquet(out_a, index=False)
    if not externo:
        shutil.rmtree(dest, ignore_errors=True)
