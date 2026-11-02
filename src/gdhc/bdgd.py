"""Extração da BDGD (PRODIST Módulo 10) no nível do transformador de distribuição.

Cada snapshot anual da BDGD é um File Geodatabase de ~1 GB (zip) com o cadastro da
rede em 31/12. Daqui saem, por transformador MT/BT:

* potência nominal (kVA), alimentador, município, área (urbana/rural) e coordenadas;
* geração distribuída conectada na baixa tensão (UGBT): nº de unidades e kW instalados;
* consumidores de baixa tensão (UCBT): nº de unidades e energia anual.

E, por alimentador (CTMT): GD de média tensão (UGMT) e consumo de MT (UCMT).

Download e leitura adaptados de ``distribution-asset-risk`` (mesmo autor), que lida com
as diferenças de nomes entre o modelo antigo da BDGD (M10) e o atual (V10/V11).
"""
from __future__ import annotations

import logging
import time
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import pyogrio
import requests

log = logging.getLogger(__name__)

ARCGIS_DATA = "https://www.arcgis.com/sharing/rest/content/items/{item}/data"
MESES = [f"ENE_{m:02d}" for m in range(1, 13)]

# Nomes que mudaram entre o modelo antigo (M10, até 2020) e o atual (V10/V11)
LAYER_ALIASES = {
    "UNTRMT": ["UNTRMT", "UNTRD"],
    "UGBT_tab": ["UGBT_tab", "UGBT"],
    "UGMT_tab": ["UGMT_tab", "UGMT"],
    "UCBT_tab": ["UCBT_tab", "UCBT"],
    "UCMT_tab": ["UCMT_tab", "UCMT"],
}
FIELD_ALIASES = {
    "NOME": ["NOME", "NOM"],
    "UNI_TR_MT": ["UNI_TR_MT", "UNI_TR_D", "UNI_TR"],
    "POT_NOM": ["POT_NOM"],
    "CTMT": ["CTMT"],
    "CEG_GD": ["CEG_GD", "CEG"],
}


def download(item: str, dest: Path, retries: int = 4) -> Path:
    """Baixa e descompacta um snapshot; devolve o caminho do .gdb."""
    dest.mkdir(parents=True, exist_ok=True)
    existing = [p for p in dest.rglob("*.gdb") if p.is_dir()]
    if existing:
        return existing[0]
    zpath = dest / f"{item}.gdb.zip"
    for attempt in range(retries):
        try:
            with requests.get(ARCGIS_DATA.format(item=item), stream=True, timeout=3000) as r:
                r.raise_for_status()
                with open(zpath, "wb") as f:
                    f.writelines(r.iter_content(1 << 22))
            break
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** (attempt + 1))
    with zipfile.ZipFile(zpath) as z:
        z.extractall(dest)
    zpath.unlink()
    return next(p for p in dest.rglob("*.gdb") if p.is_dir())


def _layer(gdb: Path, layer: str) -> str:
    disponiveis = {name for name, _ in pyogrio.list_layers(gdb)}
    for c in LAYER_ALIASES.get(layer, [layer]):
        if c in disponiveis:
            return c
    raise KeyError(f"camada {layer} não encontrada em {gdb.name}")


def read(gdb: Path, layer: str, columns: list[str], geometry: bool = False) -> pd.DataFrame:
    """Lê colunas de uma camada aceitando nomes alternativos; ausentes viram ``None``."""
    layer = _layer(gdb, layer)
    fields = set(pyogrio.read_info(gdb, layer=layer)["fields"])
    origem = {}
    for c in columns:
        alt = next((a for a in FIELD_ALIASES.get(c, [c]) if a in fields), None)
        if alt:
            origem[c] = alt
    df = pyogrio.read_dataframe(gdb, layer=layer, read_geometry=geometry, columns=list(origem.values()),
                                use_arrow=True)
    df = df.rename(columns={v: k for k, v in origem.items()})
    for c in set(columns) - set(origem):
        df[c] = None
    return df


def _str(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip()


def _num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s, errors="coerce")


def _energia_anual(df: pd.DataFrame) -> pd.Series:
    return df[MESES].apply(pd.to_numeric, errors="coerce").sum(axis=1, min_count=1)


# Microgeração é limitada a 75 kW (Lei 14.300/2022; REN ANEEL 1.000/2021). Valores maiores em UGBT são
# tratados como inconsistência cadastral, salvo quando o registro de empreendimentos da ANEEL confirma a potência.
LIMITE_MICRO_KW = 75.0
# Minigeração: até 5 MW (3 MW para algumas fontes após a Lei 14.300/2022).
LIMITE_MINI_KW = 5000.0


def limpar_potencia_gd(kw: pd.Series, ceg: pd.Series, registro: pd.Series | None = None,
                       limite: float = LIMITE_MICRO_KW) -> pd.Series:
    """Potência de GD de BT em kW.

    Usa a potência do registro de empreendimentos da ANEEL quando o código CEG é encontrado (fonte oficial,
    mesma unidade em todos os anos). Sem registro, usa a potência da BDGD se ela for compatível com
    microgeração (até ``limite``); acima disso vira ``NaN`` (inconsistência cadastral).
    """
    kw = pd.to_numeric(kw, errors="coerce").astype(float)
    kw = kw.where(kw <= limite)
    if registro is not None:
        reg = ceg.map(registro).astype(float)
        kw = reg.where(reg.notna(), kw)
    return kw


def gd_bt(gdb: Path, registro: pd.Series | None = None) -> pd.DataFrame:
    """Unidades de GD de BT com trafo e potência.

    No modelo novo da BDGD (V10/V11) elas estão em ``UGBT``. No modelo antigo (M10) a camada ``UGBT`` da
    distribuidora vem vazia; as unidades são então as UCs de BT com código CEG de GD, e a potência vem do
    registro da ANEEL.
    """
    gd = read(gdb, "UGBT_tab", ["UNI_TR_MT", "POT_INST", "SIT_ATIV", "CEG_GD"])
    origem = "UGBT"
    if gd.empty:
        gd = read(gdb, "UCBT_tab", ["UNI_TR_MT", "SIT_ATIV", "CEG_GD"])
        gd = gd[_str(gd.CEG_GD).fillna("").str.startswith("GD")]
        gd["POT_INST"] = np.nan
        origem = "UCBT.CEG"
    out = pd.DataFrame({"trafo_id": _str(gd.UNI_TR_MT), "sit": _str(gd.SIT_ATIV), "ceg": _str(gd.CEG_GD),
                        "kw": limpar_potencia_gd(gd.POT_INST, _str(gd.CEG_GD), registro).to_numpy()})
    out = out[out.sit.isna() | out.sit.eq("AT")]
    out.attrs["origem"] = origem
    return out


def trafos(gdb: Path, ano: int, registro: pd.Series | None = None) -> pd.DataFrame:
    """Uma linha por transformador MT/BT ativo, com GD e consumidores de BT agregados.

    ``registro``: potência (kW) por código CEG do registro de empreendimentos de GD da ANEEL, usada para
    corrigir potências implausíveis de BT (ver ``limpar_potencia_gd``).
    """
    tr = read(gdb, "UNTRMT", ["COD_ID", "CTMT", "POT_NOM", "MUN", "ARE_LOC", "SIT_ATIV"], geometry=True)
    tr = tr.to_crs(4326)
    out = pd.DataFrame({
        "trafo_id": _str(tr.COD_ID),
        "ctmt": _str(tr.CTMT),
        "kva": _num(tr.POT_NOM),
        "mun": _str(tr.MUN),
        "urbano": _str(tr.ARE_LOC).eq("UB"),
        "lon": tr.geometry.x.values,
        "lat": tr.geometry.y.values,
    })
    sit = _str(tr.SIT_ATIV)
    out = out[sit.isna() | sit.eq("AT")].drop_duplicates("trafo_id")

    gd = gd_bt(gdb, registro)
    n_desc = int(gd.kw.isna().sum())
    gd = gd.dropna(subset=["kw"])
    gd_tr = gd.groupby("trafo_id").agg(n_gd=("kw", "size"), gd_kw=("kw", "sum")).reset_index()

    uc = read(gdb, "UCBT_tab", ["UNI_TR_MT", "CLAS_SUB", "SIT_ATIV", *MESES])
    uc = uc.assign(trafo_id=_str(uc.UNI_TR_MT), kwh=_energia_anual(uc),
                   residencial=_str(uc.CLAS_SUB).str.startswith("RE"), sit=_str(uc.SIT_ATIV))
    uc = uc[uc.sit.isna() | uc.sit.eq("AT")]
    uc_tr = uc.groupby("trafo_id").agg(n_uc=("kwh", "size"), consumo_mwh_ano=("kwh", lambda s: s.sum() / 1e3),
                                       frac_residencial=("residencial", "mean")).reset_index()

    out = out.merge(gd_tr, on="trafo_id", how="left").merge(uc_tr, on="trafo_id", how="left")
    out[["n_gd", "gd_kw", "n_uc", "consumo_mwh_ano"]] = out[["n_gd", "gd_kw", "n_uc", "consumo_mwh_ano"]].fillna(0)
    out["ano"] = ano
    cobertura = gd.trafo_id.isin(out.trafo_id).mean() if len(gd) else np.nan
    log.info("BDGD %s: %d trafos, %d GD BT via %s (%.1f%% ligadas a um trafo ativo), %.0f MW; %d sem potência",
             ano, len(out), len(gd), gd.attrs.get("origem"), 100 * cobertura, gd.kw.sum() / 1e3, n_desc)
    out.attrs["gd_descartadas"] = n_desc
    return out


def alimentadores(gdb: Path, ano: int, registro: pd.Series | None = None) -> pd.DataFrame:
    """Uma linha por alimentador (CTMT) com consumo de MT e GD de MT.

    Só entram em ``UGMT`` as unidades com código CEG de geração distribuída (``GD...``); PCHs e térmicas
    ligadas em MT ficam de fora. A potência segue a mesma regra da BT, com o limite da minigeração.
    """
    ct = read(gdb, "CTMT", ["COD_ID", "NOME", "SUB", *MESES])
    out = pd.DataFrame({"ctmt": _str(ct.COD_ID), "alimentador": _str(ct.NOME).str.zfill(6),
                        "subestacao": _str(ct.SUB), "energia_injetada_mwh_ano": _energia_anual(ct) / 1e3})
    ucmt = read(gdb, "UCMT_tab", ["CTMT", "SIT_ATIV", *MESES])
    ucmt = ucmt.assign(ctmt=_str(ucmt.CTMT), kwh=_energia_anual(ucmt))
    cmt = ucmt.groupby("ctmt").agg(consumo_mt_mwh_ano=("kwh", lambda s: s.sum() / 1e3)).reset_index()
    gmt = read(gdb, "UGMT_tab", ["CTMT", "POT_INST", "SIT_ATIV", "CEG_GD"])
    ceg = _str(gmt.CEG_GD).fillna("")
    gmt = gmt.assign(ctmt=_str(gmt.CTMT), sit=_str(gmt.SIT_ATIV),
                     kw=limpar_potencia_gd(gmt.POT_INST, ceg, registro, LIMITE_MINI_KW).to_numpy())
    gmt = gmt[(gmt.sit.isna() | gmt.sit.eq("AT")) & ceg.str.startswith("GD").to_numpy()].dropna(subset=["kw"])
    gmt = gmt.groupby("ctmt").agg(n_gd_mt=("kw", "size"), gd_mt_kw=("kw", "sum")).reset_index()
    out = out.merge(cmt, on="ctmt", how="left").merge(gmt, on="ctmt", how="left")
    out[["consumo_mt_mwh_ano", "n_gd_mt", "gd_mt_kw"]] = out[["consumo_mt_mwh_ano", "n_gd_mt", "gd_mt_kw"]].fillna(0)
    out["ano"] = ano
    return out.drop_duplicates("ctmt")
