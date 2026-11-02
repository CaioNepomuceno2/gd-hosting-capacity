"""Figuras do README (reports/figures/*.png)."""
import json

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

from gdhc.config import ROOT, Config

cfg = Config.load()
REP = ROOT / "reports"
FIG = REP / "figures"
FIG.mkdir(parents=True, exist_ok=True)
res = json.loads((REP / "resultados.json").read_text())

# mesma paleta do distribution-asset-risk
SURFACE, INK, INK2, MUTED, GRID, AXIS = "#fcfcfb", "#0b0b0b", "#52514e", "#898781", "#e1e0d9", "#c3c2b7"
S1, S2, S3, S4 = "#2a78d6", "#eb6834", "#1baf7a", "#a35ec9"
NOME = {"modelo": "Modelo (LightGBM)", "proporcional_gd_atual": "Maior penetração hoje",
        "proporcional_ultimo_ano": "Proporcional ao último ano", "proporcional_consumidores":
        "Proporcional aos consumidores", "persistencia": "Persistência (sem crescimento)"}
COR = {"modelo": S1, "proporcional_gd_atual": S2, "proporcional_ultimo_ano": S3,
       "proporcional_consumidores": S4, "persistencia": MUTED}
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 10, "axes.facecolor": SURFACE, "figure.facecolor": SURFACE,
    "axes.edgecolor": AXIS, "axes.labelcolor": INK2, "xtick.color": MUTED, "ytick.color": MUTED,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 1, "axes.spines.top": False,
    "axes.spines.right": False, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK,
    "axes.titlelocation": "left", "legend.frameon": False, "legend.labelcolor": INK2,
})
br = FuncFormatter(lambda v, _: f"{v:,.0f}".replace(",", "."))


def salvar(fig, nome):
    fig.savefig(FIG / nome, dpi=180, bbox_inches="tight")
    plt.close(fig)


def contorno(ax):
    uf = json.loads((ROOT / "data" / "ref" / "mt_ibge.geojson").read_text())
    for feat in uf["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            xy = np.array(poly[0])
            ax.fill(xy[:, 0], xy[:, 1], color="#f0efec", ec=AXIS, lw=1, zorder=1)
    ax.grid(False)


# 1) evolução ------------------------------------------------------------------
d = pd.read_csv(REP / "diagnostico_anual.csv")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 4))
a1.bar(d.ano, d.gd_bt_mw, color=S1, label="GD na baixa tensão")
a1.bar(d.ano, d.gd_mt_mw, bottom=d.gd_bt_mw, color=S3, label="GD na média tensão")
a1.yaxis.set_major_formatter(br)
a1.set_ylabel("MW instalados (31/12)")
a1.set_title("Geração distribuída na rede da Energisa MT")
a1.legend(loc="upper left")
a2.plot(d.ano, d.frac_trafos_saturados, color=S2, lw=2.5, marker="o", mec=SURFACE, mew=2,
        label="GD ≥ 100% do kVA")
a2.plot(d.ano, d.frac_trafos_alerta, color=S2, lw=1.5, ls="--", marker="o", ms=4, label="GD ≥ 80% do kVA")
a2.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
a2.set_title("Transformadores com GD acima da capacidade")
a2.set_ylabel("% dos trafos com consumidores")
a2.legend(loc="upper left")
for ax in (a1, a2):
    ax.set_xticks(d.ano)
salvar(fig, "01_evolucao.png")

# 2) backtest -------------------------------------------------------------------
bt = pd.read_csv(REP / "backtest.csv")
b = bt[(bt.total == "total_observado") & (bt.metodo != "persistencia")].set_index("metodo")
ordem = ["modelo", "proporcional_ultimo_ano", "proporcional_gd_atual", "proporcional_consumidores"]
b = b.loc[ordem]
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.6))
y = np.arange(len(b))[::-1]
a1.barh(y, b.average_precision, color=[COR[m] for m in b.index], height=0.6)
a1.set_yticks(y, [NOME[m] for m in b.index])
a1.set_xlabel("Average precision (maior é melhor)")
a1.set_title("Quem vai saturar entre 2023 e 2025?")
for yi, v in zip(y, b.average_precision):
    a1.text(v, yi, f"  {v:.2f}".replace(".", ","), va="center", color=INK, fontsize=9)
a2.barh(y, b.acertos_top5000, color=[COR[m] for m in b.index], height=0.6)
a2.set_yticks(y, [""] * len(b))
a2.xaxis.set_major_formatter(br)
a2.set_xlabel("Trafos que de fato saturaram entre os 5 mil da lista")
a2.set_title("Lista de 5 mil trafos montada em dez/2022")
for yi, v in zip(y, b.acertos_top5000):
    a2.text(v, yi, f"  {v:,.0f}".replace(",", "."), va="center", color=INK, fontsize=9)
for ax in (a1, a2):
    ax.grid(axis="y", visible=False)
    ax.set_xlim(0, ax.get_xlim()[1] * 1.15)
salvar(fig, "02_backtest.png")

# 3) mapa ------------------------------------------------------------------------
tp = pd.read_parquet(cfg.processed / "trafos_previsao.parquet")
tp = tp[tp.n_uc > 0]
ano_base = res["previsao_totais"]["ano_base"]
cat = np.select([tp.ano_saturacao <= ano_base, tp.ano_saturacao <= ano_base + 3], ["sat", "prev"], "ok")
fig, ax = plt.subplots(figsize=(7, 7.5))
contorno(ax)
ok = tp[cat == "ok"].sample(min(20000, int((cat == "ok").sum())), random_state=0)
ax.scatter(ok.lon, ok.lat, s=1, color=AXIS, lw=0, zorder=2, label="Sem saturação prevista até " + str(ano_base + 3))
d = tp[cat == "prev"]
ax.scatter(d.lon, d.lat, s=3, color=S1, lw=0, zorder=3, label=f"Satura até {ano_base + 3} (previsto): {len(d):,}"
           .replace(",", "."))
d = tp[cat == "sat"]
ax.scatter(d.lon, d.lat, s=3, color=S2, lw=0, zorder=4, label=f"Já saturado em {ano_base}: {len(d):,}"
           .replace(",", "."))
ax.set_aspect(1 / np.cos(np.radians(tp.lat.mean())))
ax.set_xlabel("Longitude")
ax.set_ylabel("Latitude")
ax.set_title("Transformadores com GD ≥ potência nominal")
ax.legend(loc="lower left", markerscale=6)
salvar(fig, "03_mapa_trafos.png")

# 4) projeção --------------------------------------------------------------------
pj = pd.read_csv(REP / "projecao_reforco.csv")
fig, ax = plt.subplots(figsize=(7, 3.8))
ax.bar(pj.ano, pj.trafos_que_saturam, color=S1, width=0.6)
ax.yaxis.set_major_formatter(br)
ax.set_ylabel("Trafos que passam a saturar")
for x, n, rs in zip(pj.ano, pj.trafos_que_saturam, pj.reforco_rs_mi):
    ax.text(x, n, f"R$ {rs:,.0f} mi".replace(",", "."), ha="center", va="bottom", color=INK, fontsize=9)
ax.set_title(f"Projeção a partir de {ano_base}: novos trafos saturados e custo de reforço\n"
             "(ritmo de adição de GD do último ano; custos ilustrativos)")
ax.set_ylim(0, pj.trafos_que_saturam.max() * 1.18)
ax.set_xticks(pj.ano)
salvar(fig, "04_projecao.png")

# 5) validação: ampliação dos trafos e saturação por porte ------------------------------
amp = pd.read_csv(REP / "validacao_ampliacao_trafos.csv", index_col=0)
porte = pd.read_csv(REP / f"saturacao_por_porte_{ano_base}.csv")
fig, (a1, a2) = plt.subplots(1, 2, figsize=(11, 3.6))
rot = {"saturado_2022": "Saturado em dez/2022", "nao_saturado_2022": "Não saturado"}
amp = amp.loc[["nao_saturado_2022", "saturado_2022"]]
a1.bar([rot[i] for i in amp.index], amp["mean"], color=[AXIS, S2], width=0.5)
a1.set_ylabel("Trafos trocados por um maior até 2025")
a1.set_title("A distribuidora ampliou os trafos saturados?")
rot_p = {"<=10": "até 10", "15": "15", "30": "30", "45-75": "45 a 75", ">75": "acima de 75"}
a2.bar([rot_p[f] for f in porte.faixa_kva], porte.saturados, color=S1, width=0.6)
a2.set_xlabel("Potência do trafo (kVA)")
a2.set_ylabel(f"Saturados em dez/{ano_base}")
a2.set_title("Onde a GD já passou da capacidade")
for ax, vals in ((a1, amp["mean"]), (a2, porte.saturados)):
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    for x, v in enumerate(vals):
        ax.text(x, v, f"{100 * v:.1f}%".replace(".", ","), ha="center", va="bottom", color=INK, fontsize=9)
    ax.grid(axis="x", visible=False)
salvar(fig, "05_validacao.png")

print(json.dumps(sorted(p.name for p in FIG.glob("*.png"))))
