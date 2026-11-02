"""Validações externas do critério de saturação. Atualiza ``reports/resultados.json``.

* trafos saturados em dez/2022 foram trocados por um maior até dez/2025 (BDGD, ligados pela posição)?
* pedidos de conexão de MMGD de BT (2022-2023): municípios com mais trafos saturados exigem mais obras?
* GD da BDGD x registro de empreendimentos da ANEEL.

Pré-requisito: ``03_analise.py``.
"""
import json
import logging

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from gdhc import painel as P
from gdhc import rede
from gdhc.config import ROOT, Config, premissas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("validacao")
cfg = Config.load()
PR = premissas()
LIM = PR["saturacao"]["limite_trafo"]
LIM_ALERTA = PR["saturacao"]["limite_trafo_alerta"]
ANOS = sorted(cfg.bdgd_snapshots)
ORIGEM_BT, ULTIMO = 2022, max(ANOS)
OUT = ROOT / "reports"
res = json.loads((OUT / "resultados.json").read_text())
t_ult = P.carregar(cfg.interim, ULTIMO)
alim_ult = pd.read_parquet(cfg.interim / f"alimentadores_{ULTIMO}.parquet")

# (a) trafos saturados em 2022 foram trocados por maiores até 2025?
lig = P.ligar(P.carregar(cfg.interim, ORIGEM_BT), t_ult)
v = P.carregar(cfg.interim, ORIGEM_BT).merge(lig, on="trafo_id").merge(
    t_ult[["trafo_id", "kva"]].rename(columns={"trafo_id": "trafo_id_b", "kva": "kva_fut"}), on="trafo_id_b")
v = v[v.n_uc > 0]
v["sat"] = rede.saturado(v.gd_kw, v.kva, LIM)
v["ampliado"] = v.kva_fut > v.kva
up = v.groupby("sat").ampliado.agg(["mean", "size"]).rename(index={True: "saturado_2022", False: "nao_saturado_2022"})
up.to_csv(OUT / "validacao_ampliacao_trafos.csv")
res["validacao_ampliacao"] = {k: {"frac_ampliados_ate_2025": float(r["mean"]), "trafos": int(r["size"])}
                              for k, r in up.iterrows()}
log.info("trafos ampliados 2022->2025:\n%s", up)

# (b) pedidos de conexão de MMGD de BT (2022-2023): municípios com mais trafos saturados exigem mais obras?
ped = pd.read_parquet(cfg.interim / "pedidos_mmgd.parquet")
ped = ped[ped.DscSubgrupoTarifario.str.startswith("B", na=False)]
pm = ped.groupby("CodMunicipioIBGE").agg(pedidos=("NumProtocolo", "size"),
                                          frac_obras=("DscNecessidadeObras", lambda s: (s == "SIM").mean()))
t22 = P.carregar(cfg.interim, ORIGEM_BT)
t22 = t22[t22.n_uc > 0]
m22 = t22.assign(sat=rede.saturado(t22.gd_kw, t22.kva, LIM_ALERTA)).groupby("mun").agg(
    frac_alerta=("sat", "mean"), trafos=("sat", "size"), frac_urbano=("urbano", "mean"))
m22.index = pd.to_numeric(m22.index, errors="coerce")
vm = pm.join(m22, how="inner")
vm = vm[vm.pedidos >= 50]
rho = spearmanr(vm.frac_alerta, vm.frac_obras).statistic
rho_urb = spearmanr(vm.frac_urbano, vm.frac_obras).statistic
vm["quartil_alerta"] = pd.qcut(vm.frac_alerta.rank(method="first"), 4, labels=["Q1", "Q2", "Q3", "Q4"])
qt = vm.groupby("quartil_alerta", observed=True).apply(
    lambda g: pd.Series({"municipios": len(g), "frac_obras": np.average(g.frac_obras, weights=g.pedidos),
                         "frac_alerta_media": g.frac_alerta.mean()}), include_groups=False)
qt.to_csv(OUT / "validacao_pedidos_mmgd.csv")
res["validacao_pedidos"] = {"municipios": len(vm), "spearman": float(rho),
                            "spearman_obras_x_frac_trafos_urbanos": float(rho_urb),
                            "por_quartil": qt.round(4).reset_index().to_dict("records")}
log.info("pedidos MMGD x saturação municipal: rho=%.3f\n%s", rho, qt)

# (c) BDGD x registro da ANEEL
reg = pd.read_parquet(cfg.interim / "registro_gd.parquet")
res["checagem_registro"] = {"registro_aneel_mw_uf": float(reg.kw.sum() / 1e3),
                            "bdgd_gd_bt_mw_2025": float(t_ult.gd_kw.sum() / 1e3),
                            "bdgd_gd_mt_mw_2025": float(alim_ult.gd_mt_kw.sum() / 1e3)}

(OUT / "resultados.json").write_text(json.dumps(res, indent=2, ensure_ascii=False, allow_nan=False),
                                     encoding="utf-8")
