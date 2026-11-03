"""Indicadores de decisão derivados dos relatórios (não precisa dos dados brutos).

Lê ``reports/backtest_reforco_rs.csv`` e ``reports/validacao_ampliacao_trafos.csv`` e grava
``reports/resumo_decisao.csv`` e ``reports/resumo_decisao.json`` com:

* para cada regra de priorização e tamanho de lista: fração do R$ antecipado que caiu em trafos que de fato
  saturaram (o "dinheiro bem gasto") e o R$ antecipado sem necessidade;
* quantos trafos já saturados em 2022 continuavam sem troca em 2025 (o passivo que a lista atacaria).

Pré-requisito: ``03_analise.py`` e ``04_validacao.py``.
"""
import json

import pandas as pd

from gdhc.config import ROOT

OUT = ROOT / "reports"

rs = pd.read_csv(OUT / "backtest_reforco_rs.csv")
rs["rs_mi_total_antecipado"] = rs.rs_mi_em_trafos_que_saturaram + rs.rs_mi_antecipado_sem_necessidade
rs["frac_rs_bem_gasto"] = rs.rs_mi_em_trafos_que_saturaram / rs.rs_mi_total_antecipado
rs = rs[["metodo", "k", "acertos", "precisao", "rs_mi_em_trafos_que_saturaram", "rs_mi_antecipado_sem_necessidade",
         "rs_mi_total_antecipado", "frac_rs_bem_gasto"]]
rs.to_csv(OUT / "resumo_decisao.csv", index=False)

amp = pd.read_csv(OUT / "validacao_ampliacao_trafos.csv", index_col=0)
sat = amp.loc["saturado_2022"]
resumo = {
    "lista_reforco": rs.round(4).to_dict("records"),
    "saturados_2022": int(sat["size"]),
    "saturados_2022_trocados_ate_2025": round(float(sat["mean"]) * int(sat["size"])),
    "saturados_2022_sem_troca_em_2025": round((1 - float(sat["mean"])) * int(sat["size"])),
    "frac_saturados_2022_sem_troca_em_2025": float(1 - sat["mean"]),
}
(OUT / "resumo_decisao.json").write_text(json.dumps(resumo, indent=2, ensure_ascii=False), encoding="utf-8")
print(rs.round(3).to_string(index=False))
print({k: v for k, v in resumo.items() if k != "lista_reforco"})
