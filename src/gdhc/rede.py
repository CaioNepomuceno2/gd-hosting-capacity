"""Critérios de saturação, custo de reforço e projeção do ano de saturação."""
from __future__ import annotations

import numpy as np
import pandas as pd


def saturado(gd_kw, kva, limite: float):
    """Trafo saturado quando a GD instalada atinge ``limite`` x potência nominal."""
    return np.asarray(gd_kw, dtype=float) >= limite * np.asarray(kva, dtype=float)


def kva_necessario(gd_kw, limite: float):
    return np.asarray(gd_kw, dtype=float) / limite


def custo_reforco(gd_kw, kva, limite: float, tamanhos: list[float], custo_kva: float, custo_fixo: float) -> np.ndarray:
    """R$ para trocar o trafo pelo menor tamanho padrão que comporta a GD (0 se não precisa).

    Se nenhum tamanho padrão comporta a GD, usa o kVA exato necessário (caso raro de GD concentrada).
    """
    gd_kw, kva = np.asarray(gd_kw, dtype=float), np.asarray(kva, dtype=float)
    precisa = saturado(gd_kw, kva, limite)
    alvo = kva_necessario(gd_kw, limite)
    tam = np.sort(np.asarray(tamanhos, dtype=float))
    idx = np.searchsorted(tam, alvo, side="right")  # estritamente acima do necessário
    novo = np.where(idx < len(tam), tam[np.minimum(idx, len(tam) - 1)], np.ceil(alvo))
    return np.where(precisa, novo * custo_kva + custo_fixo, 0.0)


def ano_saturacao(nivel_atual, taxa_anual, capacidade, ano_base: int, ano_max: int) -> np.ndarray:
    """Primeiro ano em que ``nivel_atual + taxa_anual * t`` atinge ``capacidade`` (``NaN`` se depois de ``ano_max``).

    Já saturado no ano base -> ``ano_base``.
    """
    n, r, c = (np.asarray(v, dtype=float) for v in (nivel_atual, taxa_anual, capacidade))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.ceil((c - n) / r)
    t = np.where(n >= c, 0, np.where(r > 0, t, np.inf))
    ano = ano_base + t
    return np.where(ano <= ano_max, ano, np.nan)


def alimentadores(trafos: pd.DataFrame, alim: pd.DataFrame, fator_simult: float) -> pd.DataFrame:
    """GD (BT + MT) e carga média por alimentador; razão GD simultânea / carga média."""
    bt = trafos.groupby("ctmt").agg(gd_bt_kw=("gd_kw", "sum"), consumo_bt_mwh_ano=("consumo_mwh_ano", "sum"),
                                    n_trafos=("trafo_id", "size"), n_uc=("n_uc", "sum")).reset_index()
    df = alim.merge(bt, on="ctmt", how="left").fillna({"gd_bt_kw": 0, "consumo_bt_mwh_ano": 0, "n_trafos": 0,
                                                       "n_uc": 0})
    df["gd_total_kw"] = df.gd_bt_kw + df.gd_mt_kw
    df["carga_media_kw"] = (df.consumo_bt_mwh_ano + df.consumo_mt_mwh_ano) * 1e3 / 8760
    df["razao_gd_carga"] = df.gd_total_kw * fator_simult / df.carga_media_kw.replace(0, np.nan)
    return df
