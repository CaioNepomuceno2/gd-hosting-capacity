"""Para onde vai a próxima GD? Modelo de alocação do crescimento entre transformadores.

O total de GD que entra no sistema muda muito de um ano para outro (corrida antes da Lei 14.300, juros,
preço dos módulos), e um modelo de árvore não extrapola níveis que nunca viu. Por isso o problema é
separado em duas partes:

* **alocação**: qual fração do crescimento do sistema cai em cada trafo (``share`` do crescimento na
  janela). É aqui que a rede e o histórico local ajudam, e é o que um planejador precisa para priorizar;
* **total**: quantos kW entram no sistema na janela. Na previsão, uma regra simples e explícita (ritmo do
  último ano); no backtest, a alocação também é avaliada com o total observado, para isolar a habilidade
  de alocação.
"""
from __future__ import annotations

from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from gdhc import painel as P

FEATURES = [
    "kva", "gd_kw", "n_gd", "n_uc", "consumo_mwh_ano", "consumo_por_uc_mwh", "frac_residencial", "urbano",
    "lat", "lon", "penetracao", "folga_kw", "kva_por_uc", "folga_por_uc_sem_gd_kw", "frac_uc_com_gd",
    "trafo_novo", "share_add_1a", "n_gd_add_1a",
    "viz_gd_kw", "viz_n_uc", "viz_share_add_1a",
    "mun_gd_por_uc_kw", "mun_frac_uc_com_gd", "mun_share_add_1a", "mun_cresc_1a",
    "alim_gd_por_uc_kw", "alim_frac_uc_com_gd", "alim_share_add_1a", "alim_cresc_1a", "horizonte",
]
PARAMS = {"objective": "tweedie", "tweedie_variance_power": 1.3, "learning_rate": 0.05, "num_leaves": 63,
          "min_child_samples": 100, "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.8,
          "n_estimators": 500, "n_jobs": 2, "verbose": -1}
ESCALA = 1e6  # share do crescimento do sistema em partes por milhão


def janelas(anos: list[int], corte: int, horizontes=(1, 2, 3)) -> list[tuple[int, int]]:
    """Pares (origem, horizonte) cujo alvo é observável até ``corte`` e cuja origem tem ano anterior."""
    return [(o, h) for o in anos for h in horizontes if o - 1 in anos and o + h <= corte and o + h in anos]


def treino(interim: Path, anos: list[int], corte: int) -> pd.DataFrame:
    partes = []
    for o, h in janelas(anos, corte):
        df = P.painel(interim, o, h)
        df["share_alvo"] = df.gd_add_h / df.gd_add_h.sum() * ESCALA
        partes.append(df)
    return pd.concat(partes, ignore_index=True)


def X(df: pd.DataFrame) -> pd.DataFrame:
    return df[FEATURES].astype("float64")


def ajustar(df: pd.DataFrame, seed: int = 0) -> lgb.LGBMRegressor:
    m = lgb.LGBMRegressor(random_state=seed, **PARAMS)
    m.fit(X(df), df.share_alvo)
    return m


def alocar(modelo: lgb.LGBMRegressor, df: pd.DataFrame, total_kw: float) -> np.ndarray:
    """Distribui ``total_kw`` entre os trafos na proporção do share previsto."""
    s = np.clip(modelo.predict(X(df)), 0, None)
    return total_kw * s / s.sum()


def baselines(df: pd.DataFrame, total_kw: float) -> dict[str, np.ndarray]:
    """Regras simples de alocação do mesmo total."""
    def prop(v):
        v = np.asarray(v, dtype=float)
        return total_kw * v / v.sum() if v.sum() > 0 else np.zeros_like(v)
    return {
        "proporcional_gd_atual": prop(df.gd_kw),
        "proporcional_ultimo_ano": prop(df.gd_add_1a),
        "proporcional_consumidores": prop(df.n_uc),
    }


def total_ritmo_ultimo_ano(df: pd.DataFrame, horizonte: int) -> float:
    """Total da janela se o ritmo de adição do último ano se mantiver (regra conhecida na origem)."""
    return float(df.gd_add_1a.sum() * horizonte)


def metricas(df: pd.DataFrame, pred_add: np.ndarray, limite: float, universo: pd.Series) -> dict:
    """Erro de kW por trafo e acerto da saturação no horizonte (só trafos ainda não saturados na origem)."""
    obs_add = df.gd_add_h.to_numpy()
    sat_obs = (df.gd_kw_fut >= limite * df.kva).to_numpy()
    prev_ratio = (df.gd_kw.to_numpy() + pred_add) / df.kva.to_numpy()
    u = universo.to_numpy()
    y, s = sat_obs[u], prev_ratio[u]
    ordem = np.argsort(-s)
    out = {
        "mae_kw": float(np.mean(np.abs(obs_add - pred_add))),
        "spearman_add": float(spearmanr(obs_add, pred_add).statistic),
        "n_universo": int(u.sum()),
        "novos_saturados_obs": int(y.sum()),
        "average_precision": float(_average_precision(y, s)),
        "novos_saturados_prev": int((s >= limite).sum()),
    }
    tp = int((y & (s >= limite)).sum())
    out["precisao"] = tp / max(out["novos_saturados_prev"], 1)
    out["recall"] = tp / max(out["novos_saturados_obs"], 1)
    for k in (1000, 5000, 10000):
        out[f"acertos_top{k}"] = int(y[ordem[:k]].sum())
    return out


def _average_precision(y: np.ndarray, s: np.ndarray) -> float:
    ordem = np.argsort(-s, kind="stable")
    y = y[ordem].astype(float)
    if y.sum() == 0:
        return float("nan")
    prec = np.cumsum(y) / np.arange(1, len(y) + 1)
    return float((prec * y).sum() / y.sum())
