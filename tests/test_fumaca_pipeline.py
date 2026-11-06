"""Teste de fumaça: scripts 02 e 03 (BDGD -> trafos -> painel -> modelo -> saturação -> R$) numa rede sintética.

A "BDGD" é um GeoPackage minúsculo gerado aqui, por ano, com 240 trafos que ficam no mesmo lugar e trocam de ID
(como na BDGD real). A GD cresce mais nos trafos urbanos, então existe sinal para o modelo e há trafos que saturam.
Tudo em disco temporário, semente fixa, sem rede nem arquivos baixados.
"""
import numpy as np
import pandas as pd
import pyogrio
import pytest
from geopandas import GeoDataFrame, points_from_xy

from gdhc import bdgd, modelo, rede
from gdhc import painel as P
from gdhc.config import premissas

ANOS = [2020, 2021, 2022, 2023, 2024]
ORIGEM_BT, ULTIMO, H = 2022, 2024, 2  # backtest: origem 2022, alvo 2024 (o treino só enxerga janelas até 2022)
N, N_CTMT, KW_UNIDADE = 240, 8, 5.0
MESES = [f"ENE_{m:02d}" for m in range(1, 13)]


def _mundo(rng):
    """Atributos fixos dos trafos e unidades de GD acumuladas por ano (mais GD nos urbanos)."""
    kva = rng.choice([15.0, 30.0, 45.0, 75.0], N, p=[0.4, 0.3, 0.2, 0.1])
    urbano = rng.random(N) < 0.7
    prop = np.where(urbano, 0.8, 0.0) + 0.2 * rng.random(N)
    unidades = np.zeros((N, len(ANOS)), dtype=int)
    unidades[:, 0] = 1 + rng.poisson(prop)  # já existe GD no primeiro snapshot
    for k in range(1, len(ANOS)):
        unidades[:, k] = unidades[:, k - 1] + rng.poisson(0.1 + 0.5 * prop * (1 + 0.5 * k))
    return kva, urbano, unidades


def _gravar_gdb(destino, k, ano, rng, kva, urbano, unidades):
    """Um snapshot da BDGD (UNTRMT, UGBT, UCBT, CTMT, UCMT, UGMT) em GeoPackage; devolve os IDs dos trafos."""
    ids = np.array([f"{ano}-{j:04d}" for j in rng.permutation(N)])  # o ID muda a cada ano; a posição, não
    lat = -15.0 + (np.arange(N) // 16) * 0.0009 + rng.uniform(-3e-6, 3e-6, N)  # grade de ~100 m
    lon = -56.0 + (np.arange(N) % 16) * 0.0009 + rng.uniform(-3e-6, 3e-6, N)
    ctmt = np.array([f"C{i % N_CTMT}" for i in range(N)])
    trafos = GeoDataFrame({"COD_ID": ids, "CTMT": ctmt, "POT_NOM": kva, "MUN": [f"M{i % 5}" for i in range(N)],
                           "ARE_LOC": np.where(urbano, "UB", "RU"), "SIT_ATIV": "AT"},
                          geometry=points_from_xy(lon, lat), crs=4674)
    ugbt = pd.DataFrame([{"UNI_TR_MT": ids[i], "POT_INST": KW_UNIDADE, "SIT_ATIV": "AT",
                          "CEG_GD": f"GD.BR.{ano}.{i}.{u}"} for i in range(N) for u in range(unidades[i, k])])
    if ano == ULTIMO:  # duas potências implausíveis: uma o registro da ANEEL corrige, a outra é descartada
        ugbt = pd.concat([ugbt, pd.DataFrame([
            {"UNI_TR_MT": ids[0], "POT_INST": 43400.0, "SIT_ATIV": "AT", "CEG_GD": "GD.BR.REGISTRADA"},
            {"UNI_TR_MT": ids[1], "POT_INST": 300.0, "SIT_ATIV": "AT", "CEG_GD": "GD.BR.SEM.REGISTRO"}])])
    n_uc = rng.integers(2, 12, N)
    ucbt = pd.DataFrame([{"UNI_TR_MT": ids[i], "CLAS_SUB": "RE1" if urbano[i] else "RU1", "SIT_ATIV": "AT",
                          **dict.fromkeys(MESES, 150.0)} for i in range(N) for _ in range(n_uc[i])])
    ct = pd.DataFrame({"COD_ID": [f"C{c}" for c in range(N_CTMT)], "NOME": [f"{c + 1:03d}" for c in range(N_CTMT)],
                       "SUB": [f"S{c // 4}" for c in range(N_CTMT)], **dict.fromkeys(MESES, 1e6)})
    ucmt = pd.DataFrame({"CTMT": [f"C{c}" for c in range(N_CTMT)], "SIT_ATIV": "AT", **dict.fromkeys(MESES, 5e4)})
    ugmt = pd.DataFrame({"CTMT": ["C0", "C1"], "POT_INST": [500.0 * (k + 1), 1000.0], "SIT_ATIV": "AT",
                         "CEG_GD": ["GD.BR.MT.0", "GD.BR.MT.1"]})
    pyogrio.set_gdal_config_options({"OGR_SQLITE_SYNCHRONOUS": "OFF"})  # sem fsync a cada camada: bem mais rápido
    try:
        pyogrio.write_dataframe(trafos, destino, layer="UNTRMT", driver="GPKG")
        _gravar_tabelas(destino, ugbt, ucbt, ct, ucmt, ugmt)
    finally:
        pyogrio.set_gdal_config_options({"OGR_SQLITE_SYNCHRONOUS": None})
    return ids


def _gravar_tabelas(destino, ugbt, ucbt, ct, ucmt, ugmt):
    for nome, df in [("UGBT_tab", ugbt), ("UCBT_tab", ucbt), ("CTMT", ct), ("UCMT_tab", ucmt), ("UGMT_tab", ugmt)]:
        pyogrio.write_dataframe(df, destino, layer=nome, driver="GPKG", append=True)


def test_fumaca_pipeline_bdgd_painel_modelo_saturacao(tmp_path, monkeypatch):
    # modelo pequeno e de um só fio: o teste fica rápido e determinístico
    for chave, valor in {"n_estimators": 40, "num_leaves": 15, "min_child_samples": 10, "n_jobs": 1,
                         "learning_rate": 0.1}.items():
        monkeypatch.setitem(modelo.PARAMS, chave, valor)
    pr = premissas()
    lim, fs, rf = pr["saturacao"]["limite_trafo"], pr["saturacao"]["fator_simultaneidade_solar"], pr["reforco"]
    ano_max = pr["previsao"]["ano_maximo_saturacao"]

    def custo(gd, kva):
        return rede.custo_reforco(gd, kva, lim, rf["tamanhos_padrao_kva"], rf["custo_por_kva_rs"],
                                  rf["custo_fixo_troca_rs"])

    interim = tmp_path / "interim"
    interim.mkdir()
    rng = np.random.default_rng(2024)
    kva, urbano, unidades = _mundo(rng)
    registro = pd.Series({"GD.BR.REGISTRADA": 43.4}, name="kw")

    # script 02: cada snapshot vira trafos_<ano>.parquet e alimentadores_<ano>.parquet
    ids = {}
    for k, ano in enumerate(ANOS):
        gdb = tmp_path / f"bdgd_{ano}.gpkg"
        ids[ano] = _gravar_gdb(gdb, k, ano, rng, kva, urbano, unidades)
        t = bdgd.trafos(gdb, ano, registro)
        t.to_parquet(interim / f"trafos_{ano}.parquet", index=False)
        bdgd.alimentadores(gdb, ano, registro).to_parquet(interim / f"alimentadores_{ano}.parquet", index=False)
        assert len(t) == N and t.n_uc.gt(0).all()
        if ano == ULTIMO:
            assert t.attrs["gd_descartadas"] == 1  # a de 300 kW sem registro
    ult = P.carregar(interim, ULTIMO).set_index("trafo_id")
    # a de 43.400 kW foi corrigida pelo registro para 43,4 kW
    assert ult.loc[ids[ULTIMO][0], "gd_kw"] == pytest.approx(KW_UNIDADE * unidades[0, -1] + 43.4)
    assert ult.loc[ids[ULTIMO][1], "gd_kw"] == pytest.approx(KW_UNIDADE * unidades[1, -1])  # a de 300 kW saiu
    assert ult.gd_kw.sum() == pytest.approx(KW_UNIDADE * unidades[:, -1].sum() + 43.4)

    # script 03, parte 1: diagnóstico por ano; a GD só cresce e o trafo não muda, então a saturação só sobe
    sat, reforco, alim = [], [], {}
    for ano in ANOS:
        t = P.carregar(interim, ano)
        fa = rede.alimentadores(t, pd.read_parquet(interim / f"alimentadores_{ano}.parquet"), fs)
        alim[ano] = fa
        sat.append(int(rede.saturado(t.gd_kw, t.kva, lim).sum()))
        reforco.append(float(custo(t.gd_kw, t.kva).sum()))
        assert (fa.razao_gd_carga >= 0).all() and (fa.gd_total_kw == fa.gd_bt_kw + fa.gd_mt_kw).all()
    assert sat == sorted(sat) and sat[-1] > sat[0] and reforco == sorted(reforco)
    assert alim[ULTIMO].gd_bt_kw.sum() == pytest.approx(ult.gd_kw.sum())

    # script 03, parte 2: backtest (treino só com janelas observáveis até a origem) e alocação do crescimento
    assert modelo.janelas(ANOS, ORIGEM_BT) == [(2021, 1)]
    treino = modelo.treino(interim, ANOS, ORIGEM_BT)
    teste = P.painel(interim, ORIGEM_BT, H)
    teste = teste[teste.n_uc > 0].reset_index(drop=True)
    assert len(teste) >= 0.98 * N and (teste.gd_add_h >= 0).all()  # o vizinho mais próximo religa os trafos
    mod = modelo.ajustar(treino, seed=0)
    total = float(teste.gd_add_h.sum())
    assert total > 0
    alocs = {"modelo": modelo.alocar(mod, teste, total), **modelo.baselines(teste, total)}
    universo = pd.Series(~rede.saturado(teste.gd_kw, teste.kva, lim))
    for nome, pred in alocs.items():
        assert pred.sum() == pytest.approx(total), nome  # a alocação conserva o total
        assert (pred >= 0).all(), nome
        m = modelo.metricas(teste, pred, lim, universo)
        assert 0 <= m["precisao"] <= 1 and 0 <= m["recall"] <= 1, nome
        assert m["novos_saturados_obs"] > 0 and 0 <= m["average_precision"] <= 1, nome  # há saturação para acertar
        assert m["acertos_top1000"] <= m["novos_saturados_obs"] and m["mae_kw"] >= 0, nome
    ap = {n: modelo.metricas(teste, p, lim, universo)["average_precision"] for n, p in alocs.items()}
    assert modelo.metricas(teste, alocs["modelo"], lim, universo)["spearman_add"] > 0  # aprende o sinal planejado
    assert ap["modelo"] > ap["proporcional_consumidores"]  # e vale mais que a regra que ignora a urbanização

    # R$ da lista de reforço antecipado: dinheiro em trafos que saturaram e dinheiro sem necessidade
    sat_fut = rede.saturado(teste.gd_kw_fut, teste.kva, lim) & universo.to_numpy()
    custo_fut = custo(teste.gd_kw_fut, teste.kva)
    assert (custo_fut >= 0).all() and (custo_fut[~rede.saturado(teste.gd_kw_fut, teste.kva, lim)] == 0).all()
    score = np.where(universo, (teste.gd_kw + alocs["modelo"]) / teste.kva, -np.inf)
    sel = np.argsort(-score)[:20]
    assert 0 <= sat_fut[sel].mean() <= 1 and custo_fut[sel][sat_fut[sel]].sum() >= 0

    # script 03, parte 3: previsão a partir do último snapshot e ano de saturação de cada trafo
    treino_f = modelo.treino(interim, ANOS, ULTIMO)
    assert len(treino_f) > len(treino)
    atual = P.painel(interim, ULTIMO, H, com_alvo=False)
    atual["horizonte"] = H
    total_f = modelo.total_ritmo_ultimo_ano(atual, H)
    atual["gd_add_prev"] = modelo.alocar(modelo.ajustar(treino_f, seed=0), atual, total_f)
    assert atual.gd_add_prev.sum() == pytest.approx(total_f) and (atual.gd_add_prev >= 0).all()
    atual["taxa_anual_kw"] = atual.gd_add_prev / H
    ano_sat = rede.ano_saturacao(atual.gd_kw, atual.taxa_anual_kw, lim * atual.kva, ULTIMO, ano_max)
    ja = rede.saturado(atual.gd_kw, atual.kva, lim)
    assert (ano_sat[ja] == ULTIMO).all()  # já saturado no ano-base
    depois = ano_sat[~np.isnan(ano_sat)]
    assert ((depois >= ULTIMO) & (depois <= ano_max)).all() and (depois > ULTIMO).any()
    sem_ritmo = ~ja & (atual.taxa_anual_kw.to_numpy() == 0)
    assert np.isnan(ano_sat[sem_ritmo]).all()  # sem crescimento previsto, nunca satura
    acumulado = [int(((~np.isnan(ano_sat)) & (ano_sat <= a)).sum()) for a in range(ULTIMO, ULTIMO + 6)]
    assert acumulado == sorted(acumulado) and acumulado[0] == int(ja.sum())
