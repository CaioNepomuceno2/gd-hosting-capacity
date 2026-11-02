"""Painel de transformadores entre snapshots da BDGD, sem informação futura.

Os códigos dos transformadores (``COD_ID``) mudam entre snapshots, então o mesmo trafo é reconhecido pela
posição: vizinho mais próximo mútuo a no máximo ``max_m`` metros. Isso liga ~99% dos trafos entre 2022 e 2025.

Enquadramento da previsão (origem ``o``, horizonte ``h``):

* features: só o snapshot de 31/12/``o`` e os anteriores (crescimento recente);
* alvo: kW de GD adicionados no trafo entre ``o`` e ``o + h``, medidos no snapshot ``o + h``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

R_TERRA_M = 6_371_000.0


def ligar(a: pd.DataFrame, b: pd.DataFrame, max_m: float = 20.0) -> pd.DataFrame:
    """Liga trafos de dois snapshots por vizinho mais próximo mútuo. Devolve ``trafo_id`` -> ``trafo_id_b``."""
    A = np.radians(a[["lat", "lon"]].to_numpy())
    B = np.radians(b[["lat", "lon"]].to_numpy())
    dab, iab = BallTree(B, metric="haversine").query(A, k=1)
    _, iba = BallTree(A, metric="haversine").query(B, k=1)
    dab, iab, iba = dab[:, 0] * R_TERRA_M, iab[:, 0], iba[:, 0]
    ok = (iba[iab] == np.arange(len(a))) & (dab <= max_m)
    return pd.DataFrame({"trafo_id": a.trafo_id.to_numpy()[ok], "trafo_id_b": b.trafo_id.to_numpy()[iab[ok]],
                         "dist_m": dab[ok]})


def soma_vizinhanca(df: pd.DataFrame, valor: str, raio_m: float) -> np.ndarray:
    """Soma de ``valor`` nos outros trafos a até ``raio_m`` metros de cada trafo."""
    X = np.radians(df[["lat", "lon"]].to_numpy())
    tree = BallTree(X, metric="haversine")
    idx = tree.query_radius(X, r=raio_m / R_TERRA_M)
    v = df[valor].to_numpy()
    return np.array([v[i].sum() for i in idx]) - v


_CACHE: dict = {}


def carregar(interim: Path, ano: int) -> pd.DataFrame:
    return pd.read_parquet(interim / f"trafos_{ano}.parquet")


def features(interim: Path, origem: int, raio_m: float = 500.0) -> pd.DataFrame:
    """Uma linha por trafo do snapshot ``origem`` com features disponíveis em 31/12/``origem``."""
    chave = (str(interim), origem, raio_m)
    if chave not in _CACHE:
        _CACHE[chave] = _features(interim, origem, raio_m)
    return _CACHE[chave].copy()


def _features(interim: Path, origem: int, raio_m: float) -> pd.DataFrame:
    t = carregar(interim, origem).copy()
    ant = carregar(interim, origem - 1)
    lig = ligar(t, ant).rename(columns={"trafo_id_b": "trafo_ant"})
    t = t.merge(lig[["trafo_id", "trafo_ant"]], on="trafo_id", how="left")
    t = t.merge(ant[["trafo_id", "gd_kw", "n_gd"]].rename(
        columns={"trafo_id": "trafo_ant", "gd_kw": "gd_kw_ant", "n_gd": "n_gd_ant"}), on="trafo_ant", how="left")
    t["trafo_novo"] = t.trafo_ant.isna()
    t[["gd_kw_ant", "n_gd_ant"]] = t[["gd_kw_ant", "n_gd_ant"]].fillna(0)
    t["gd_add_1a"] = (t.gd_kw - t.gd_kw_ant).clip(lower=0)
    t["n_gd_add_1a"] = (t.n_gd - t.n_gd_ant).clip(lower=0)
    total_add = t.gd_add_1a.sum()

    t["penetracao"] = t.gd_kw / t.kva
    t["folga_kw"] = t.kva - t.gd_kw
    t["consumo_por_uc_mwh"] = t.consumo_mwh_ano / t.n_uc.replace(0, np.nan)
    t["kva_por_uc"] = t.kva / t.n_uc.replace(0, np.nan)
    t["folga_por_uc_sem_gd_kw"] = t.folga_kw / (t.n_uc - t.n_gd).clip(lower=1)
    t["frac_uc_com_gd"] = (t.n_gd / t.n_uc.replace(0, np.nan)).clip(upper=1)
    t["share_add_1a"] = t.gd_add_1a / total_add if total_add > 0 else 0.0
    # contágio espacial: GD instalada e adicionada no último ano na vizinhança
    t["viz_gd_kw"] = soma_vizinhanca(t, "gd_kw", raio_m)
    t["viz_add_1a_kw"] = soma_vizinhanca(t, "gd_add_1a", raio_m)
    t["viz_n_uc"] = soma_vizinhanca(t, "n_uc", raio_m)
    t["viz_share_add_1a"] = t.viz_add_1a_kw / total_add if total_add > 0 else 0.0
    # município e alimentador
    for chave, pref in [("mun", "mun"), ("ctmt", "alim")]:
        g = t.groupby(chave).agg(gd=("gd_kw", "sum"), add=("gd_add_1a", "sum"), uc=("n_uc", "sum"),
                                 ngd=("n_gd", "sum"))
        g[f"{pref}_gd_por_uc_kw"] = g.gd / g.uc.replace(0, np.nan)
        g[f"{pref}_frac_uc_com_gd"] = g.ngd / g.uc.replace(0, np.nan)
        g[f"{pref}_share_add_1a"] = g["add"] / total_add if total_add > 0 else 0.0
        g[f"{pref}_cresc_1a"] = g["add"] / (g.gd - g["add"]).replace(0, np.nan)
        cols = [c for c in g.columns if c.startswith(pref + "_")]
        t = t.merge(g[cols].reset_index(), on=chave, how="left")
    t["origem"] = origem
    return t


def alvo(interim: Path, origem: int, horizonte: int) -> pd.DataFrame:
    """kW de GD e kVA no snapshot ``origem + horizonte`` para cada trafo da origem (ligados pela posição)."""
    a, b = carregar(interim, origem), carregar(interim, origem + horizonte)
    lig = ligar(a, b)
    out = lig.merge(b[["trafo_id", "gd_kw", "kva"]].rename(
        columns={"trafo_id": "trafo_id_b", "gd_kw": "gd_kw_fut", "kva": "kva_fut"}), on="trafo_id_b")
    return out[["trafo_id", "gd_kw_fut", "kva_fut"]]


def painel(interim: Path, origem: int, horizonte: int, com_alvo: bool = True) -> pd.DataFrame:
    """Features da origem e, se ``com_alvo``, o crescimento observado no horizonte."""
    df = features(interim, origem)
    if com_alvo:
        df = df.merge(alvo(interim, origem, horizonte), on="trafo_id", how="inner")
        df["gd_add_h"] = (df.gd_kw_fut - df.gd_kw).clip(lower=0)
        df["horizonte"] = horizonte
    return df
