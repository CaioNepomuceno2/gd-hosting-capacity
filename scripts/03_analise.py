"""Diagnóstico, backtest point-in-time, previsão do ano de saturação e R$ de reforço.

Pré-requisitos: ``01_baixar_aneel.py`` e ``02_build_bdgd.py``.
Saídas: ``reports/*.csv``, ``reports/resultados.json`` e ``data/processed/*.parquet``.
"""
import json
import logging
import os

os.environ.setdefault("OMP_NUM_THREADS", "2")

import numpy as np
import pandas as pd

from gdhc import modelo as M
from gdhc import painel as P
from gdhc import rede
from gdhc.config import ROOT, Config, premissas

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("analise")
cfg = Config.load()
PR = premissas()
LIM = PR["saturacao"]["limite_trafo"]
LIM_ALERTA = PR["saturacao"]["limite_trafo_alerta"]
FS = PR["saturacao"]["fator_simultaneidade_solar"]
LIM_ALIM = PR["saturacao"]["limite_alimentador"]
RF = PR["reforco"]
H = PR["previsao"]["horizonte_anos"]
ANO_MAX = PR["previsao"]["ano_maximo_saturacao"]
ANOS = sorted(cfg.bdgd_snapshots)
ORIGEM_BT, ULTIMO = 2022, max(ANOS)
OUT = ROOT / "reports"
OUT.mkdir(exist_ok=True)


def custo(gd, kva):
    return rede.custo_reforco(gd, kva, LIM, RF["tamanhos_padrao_kva"], RF["custo_por_kva_rs"],
                              RF["custo_fixo_troca_rs"])


res: dict = {"premissas": PR}

# ------------------------------------------------------------------ 1. diagnóstico 2018-2025
linhas, alim_ano = [], {}
for ano in ANOS:
    t = P.carregar(cfg.interim, ano)
    a = pd.read_parquet(cfg.interim / f"alimentadores_{ano}.parquet")
    u = t[t.n_uc > 0]
    fa = rede.alimentadores(t, a, FS)
    alim_ano[ano] = fa
    linhas.append({
        "ano": ano, "trafos": len(t), "trafos_com_uc": len(u), "unidades_gd_bt": int(t.n_gd.sum()),
        "gd_bt_mw": t.gd_kw.sum() / 1e3, "gd_mt_mw": a.gd_mt_kw.sum() / 1e3,
        "frac_trafos_com_gd": float((u.gd_kw > 0).mean()),
        "frac_trafos_saturados": float(rede.saturado(u.gd_kw, u.kva, LIM).mean()),
        "frac_trafos_alerta": float(rede.saturado(u.gd_kw, u.kva, LIM_ALERTA).mean()),
        "trafos_saturados": int(rede.saturado(u.gd_kw, u.kva, LIM).sum()),
        "frac_alimentadores_acima": float((fa.razao_gd_carga >= LIM_ALIM).mean()),
        "alimentadores_acima": int((fa.razao_gd_carga >= LIM_ALIM).sum()),
        "reforco_acumulado_rs_mi": float(custo(u.gd_kw, u.kva).sum() / 1e6),
    })
diag = pd.DataFrame(linhas)
diag.to_csv(OUT / "diagnostico_anual.csv", index=False)
res["diagnostico"] = diag.round(4).to_dict("records")
log.info("diagnóstico:\n%s", diag.round(3).to_string(index=False))

t_ult = P.carregar(cfg.interim, ULTIMO)
u_ult = t_ult[t_ult.n_uc > 0].copy()
u_ult["saturado"] = rede.saturado(u_ult.gd_kw, u_ult.kva, LIM)
mun = u_ult.groupby("mun").agg(trafos=("trafo_id", "size"), saturados=("saturado", "sum"),
                               gd_mw=("gd_kw", lambda s: s.sum() / 1e3)).reset_index()
mun["frac_saturados"] = mun.saturados / mun.trafos
mun = mun.merge(pd.read_parquet(cfg.interim / "municipios.parquet").drop_duplicates("mun"), on="mun", how="left")
mun.sort_values("saturados", ascending=False).to_csv(OUT / f"municipios_{ULTIMO}.csv", index=False)
# por porte do trafo
u_ult["faixa_kva"] = pd.cut(u_ult.kva, [0, 10, 15, 30, 75, 1e9], labels=["<=10", "15", "30", "45-75", ">75"])
porte = u_ult.groupby("faixa_kva", observed=True).agg(trafos=("trafo_id", "size"), saturados=("saturado", "mean"))
porte.to_csv(OUT / f"saturacao_por_porte_{ULTIMO}.csv")

# ------------------------------------------------------------------ 2. backtest: origem 2022, horizonte 3 anos
log.info("backtest: treino com janelas observáveis até %d", ORIGEM_BT)
treino = M.treino(cfg.interim, ANOS, corte=ORIGEM_BT)
log.info("janelas de treino: %s (%d linhas)", M.janelas(ANOS, ORIGEM_BT), len(treino))
teste = P.painel(cfg.interim, ORIGEM_BT, H)
teste = teste[teste.n_uc > 0].reset_index(drop=True)
universo = pd.Series(~rede.saturado(teste.gd_kw, teste.kva, LIM))
modelos = [M.ajustar(treino, seed=s) for s in range(3)]

total_obs = float(teste.gd_add_h.sum())
total_ritmo = M.total_ritmo_ultimo_ano(teste, H)
res["backtest_totais"] = {"origem": ORIGEM_BT, "horizonte": H, "total_observado_mw": total_obs / 1e3,
                          "total_ritmo_ultimo_ano_mw": total_ritmo / 1e3,
                          "erro_total_ritmo_pct": 100 * (total_ritmo / total_obs - 1)}
bt_linhas, preds = [], {}
for nome_total, total in [("total_observado", total_obs), ("ritmo_ultimo_ano", total_ritmo)]:
    alocs = {"modelo": np.mean([M.alocar(m, teste, total) for m in modelos], axis=0), **M.baselines(teste, total)}
    for metodo, pred in alocs.items():
        bt_linhas.append({"total": nome_total, "metodo": metodo, **M.metricas(teste, pred, LIM, universo)})
        if nome_total == "total_observado":
            preds[metodo] = pred
    bt_linhas.append({"total": nome_total, "metodo": "persistencia",
                      **M.metricas(teste, np.zeros(len(teste)), LIM, universo)})
bt = pd.DataFrame(bt_linhas)
bt.to_csv(OUT / "backtest.csv", index=False)
res["backtest"] = bt.round(4).to_dict("records")
log.info("backtest:\n%s", bt.round(3).to_string(index=False))

# R$: lista de K trafos para reforço antecipado em 2022; quanto do dinheiro cai em trafos que saturaram até 2025
sat_fut = rede.saturado(teste.gd_kw_fut, teste.kva, LIM) & universo.to_numpy()
custo_fut = custo(teste.gd_kw_fut, teste.kva)  # reforço que o trafo de fato precisou
custo_padrao = custo(np.maximum(teste.gd_kw_fut, teste.kva * LIM + 1e-6), teste.kva)  # troca mínima
rs_linhas = []
for metodo, pred in preds.items():
    score = np.where(universo, (teste.gd_kw + pred) / teste.kva, -np.inf)
    ordem = np.argsort(-score)
    for k in (1000, 2000, 5000):
        sel = ordem[:k]
        acerto = sat_fut[sel]
        rs_linhas.append({"metodo": metodo, "k": k, "acertos": int(acerto.sum()), "precisao": float(acerto.mean()),
                          "rs_mi_em_trafos_que_saturaram": float(custo_fut[sel][acerto].sum() / 1e6),
                          "rs_mi_antecipado_sem_necessidade": float(custo_padrao[sel][~acerto].sum() / 1e6)})
rs = pd.DataFrame(rs_linhas)
rs.to_csv(OUT / "backtest_reforco_rs.csv", index=False)
res["backtest_reforco"] = rs.round(4).to_dict("records")
log.info("R$ por lista de K trafos:\n%s", rs.round(3).to_string(index=False))

# calibração da alocação por decil (total observado)
cal = pd.DataFrame({"prev": preds["modelo"], "obs": teste.gd_add_h})
cal["decil"] = pd.qcut(cal.prev.rank(method="first"), 10, labels=False) + 1
cal.groupby("decil")[["prev", "obs"]].mean().to_csv(OUT / "calibracao_alocacao.csv")

# ------------------------------------------------------------------ 3. previsão a partir de 2025
log.info("previsão: treino com janelas até %d", ULTIMO)
treino_f = M.treino(cfg.interim, ANOS, corte=ULTIMO)
atual = P.painel(cfg.interim, ULTIMO, H, com_alvo=False)
atual["horizonte"] = H
total_f = M.total_ritmo_ultimo_ano(atual, H)
mods_f = [M.ajustar(treino_f, seed=s) for s in range(3)]
atual["gd_add_prev_3a"] = np.mean([M.alocar(m, atual, total_f) for m in mods_f], axis=0)
atual["taxa_anual_kw"] = atual.gd_add_prev_3a / H
uc = atual.n_uc > 0
atual["ano_saturacao"] = np.where(uc, rede.ano_saturacao(atual.gd_kw, atual.taxa_anual_kw, LIM * atual.kva,
                                                         ULTIMO, ANO_MAX), np.nan)
res["previsao_totais"] = {"ano_base": ULTIMO, "adicao_prevista_3a_mw": total_f / 1e3,
                          "regra_total": "ritmo de adição do último ano mantido"}
# capex por ano: cada trafo é reforçado no ano em que satura, com a GD projetada daquele ano
proj = []
for ano in range(ULTIMO + 1, ULTIMO + 6):
    gd_ano = atual.gd_kw + atual.taxa_anual_kw * (ano - ULTIMO)
    novo = uc & (atual.ano_saturacao == ano)
    proj.append({"ano": ano, "trafos_que_saturam": int(novo.sum()),
                 "reforco_rs_mi": float(custo(gd_ano[novo], atual.kva[novo]).sum() / 1e6),
                 "trafos_saturados_acumulado": int((uc & (atual.ano_saturacao <= ano)).sum())})
proj = pd.DataFrame(proj)
proj.to_csv(OUT / "projecao_reforco.csv", index=False)
res["projecao"] = proj.round(3).to_dict("records")
log.info("projeção:\n%s", proj.round(2).to_string(index=False))

# alimentadores: GD BT projetada + GD MT no ritmo de 2022-2025 (por nome operacional, estável)
fa = alim_ano[ULTIMO].copy()
add_bt = atual.groupby("ctmt").taxa_anual_kw.sum()
fa["taxa_bt_kw"] = fa.ctmt.map(add_bt).fillna(0)
mt_antes = alim_ano[ORIGEM_BT].groupby("alimentador").gd_mt_kw.sum()
fa["taxa_mt_kw"] = ((fa.gd_mt_kw - fa.alimentador.map(mt_antes)).clip(lower=0) / (ULTIMO - ORIGEM_BT)).fillna(0)
fa = fa[fa.carga_media_kw > 0].copy()  # alimentadores sem consumo cadastrado ficam fora do critério
fa["ano_saturacao"] = rede.ano_saturacao(fa.gd_total_kw * FS, (fa.taxa_bt_kw + fa.taxa_mt_kw) * FS,
                                         LIM_ALIM * fa.carga_media_kw, ULTIMO, ANO_MAX)
# sensibilidade ao fator de simultaneidade (o critério de alimentador é só uma triagem)
sens = pd.DataFrame([{"fator_simultaneidade": f, "frac_alimentadores_acima": float(
    (fa.gd_total_kw * f >= LIM_ALIM * fa.carga_media_kw).mean())} for f in (0.3, 0.5, 0.7, 0.9)])
sens.to_csv(OUT / "sensibilidade_alimentadores.csv", index=False)
res["sensibilidade_alimentadores"] = sens.round(4).to_dict("records")
res["sistema"] = {"gd_total_mw": float(fa.gd_total_kw.sum() / 1e3), "carga_media_mw": float(
    fa.carga_media_kw.sum() / 1e3), "alimentadores_com_carga": len(fa)}
fa.to_parquet(cfg.processed / "alimentadores_previsao.parquet", index=False)
alim_resumo = (fa.assign(ano=fa.ano_saturacao.fillna(9999)).groupby("ano").size().rename("alimentadores")
               .reset_index())
alim_resumo.to_csv(OUT / "alimentadores_ano_saturacao.csv", index=False)
res["alimentadores_ano_saturacao"] = alim_resumo.to_dict("records")
fa[["alimentador", "subestacao", "gd_total_kw", "carga_media_kw", "razao_gd_carga", "taxa_bt_kw", "taxa_mt_kw",
    "ano_saturacao"]].sort_values(["ano_saturacao", "razao_gd_carga"], ascending=[True, False]).to_csv(
    OUT / "alimentadores_previsao.csv", index=False)

cols = ["trafo_id", "ctmt", "mun", "kva", "gd_kw", "n_uc", "n_gd", "lat", "lon", "gd_add_prev_3a", "taxa_anual_kw",
        "ano_saturacao"]
atual[cols].to_parquet(cfg.processed / "trafos_previsao.parquet", index=False)

def _limpo(o):
    if isinstance(o, dict):
        return {str(k): _limpo(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_limpo(v) for v in o]
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    return o


(OUT / "resultados.json").write_text(json.dumps(_limpo(res), indent=2, ensure_ascii=False, allow_nan=False),
                                     encoding="utf-8")
log.info("ok")
