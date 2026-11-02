import numpy as np
import pandas as pd

from gdhc import bdgd, modelo
from gdhc import painel as P


def _trafos(ids, lats, lons, gd=None):
    n = len(ids)
    return pd.DataFrame({"trafo_id": ids, "lat": lats, "lon": lons,
                         "gd_kw": gd if gd is not None else [0.0] * n})


def test_ligar_por_vizinho_mais_proximo_mutuo():
    a = _trafos(["a1", "a2", "a3"], [-15.0, -15.001, -16.0], [-56.0, -56.0, -56.0])
    # b1 a ~1 m de a1; b2 a ~5 m de a2; nada perto de a3
    b = _trafos(["b1", "b2"], [-15.00001, -15.00105], [-56.0, -56.0])
    lig = P.ligar(a, b, max_m=20)
    assert dict(zip(lig.trafo_id, lig.trafo_id_b)) == {"a1": "b1", "a2": "b2"}


def test_ligar_respeita_distancia_maxima():
    a = _trafos(["a1"], [-15.0], [-56.0])
    b = _trafos(["b1"], [-15.001], [-56.0])  # ~111 m
    assert P.ligar(a, b, max_m=20).empty
    assert len(P.ligar(a, b, max_m=200)) == 1


def test_soma_vizinhanca_exclui_o_proprio():
    df = pd.DataFrame({"lat": [-15.0, -15.0001, -15.1], "lon": [-56.0] * 3, "v": [1.0, 2.0, 4.0]})
    out = P.soma_vizinhanca(df, "v", raio_m=100)
    assert list(out) == [2.0, 1.0, 0.0]


def test_limpar_potencia_gd():
    kw = pd.Series([5.0, 43400.0, 300.0, 75.0, np.nan])
    ceg = pd.Series(["A", "B", "C", "D", "E"])
    reg = pd.Series({"B": 43.4, "D": 70.0, "E": 8.0})
    out = bdgd.limpar_potencia_gd(kw, ceg, reg)
    # registro tem prioridade; sem registro, só aceita até 75 kW
    assert out.tolist()[:2] == [5.0, 43.4] and np.isnan(out.iloc[2])
    assert out.iloc[3] == 70.0 and out.iloc[4] == 8.0
    sem_reg = bdgd.limpar_potencia_gd(kw, ceg, None)
    assert sem_reg.iloc[0] == 5.0 and np.isnan(sem_reg.iloc[1]) and sem_reg.iloc[3] == 75.0


def test_janelas_nao_usam_alvo_depois_do_corte():
    anos = list(range(2018, 2026))
    js = modelo.janelas(anos, corte=2022)
    assert js and all(o + h <= 2022 for o, h in js)
    assert all(o - 1 in anos for o, _ in js)  # a origem precisa do ano anterior para o crescimento recente
    assert (2019, 3) in js and (2020, 3) not in js


def test_metricas_saturacao():
    df = pd.DataFrame({"gd_kw": [0.0, 5.0, 9.0], "kva": [10.0, 10.0, 10.0],
                       "gd_kw_fut": [12.0, 6.0, 9.0]})
    df["gd_add_h"] = df.gd_kw_fut - df.gd_kw
    pred = np.array([11.0, 0.0, 2.0])  # acerta o 1º, erra o 3º (falso positivo)
    m = modelo.metricas(df, pred, limite=1.0, universo=pd.Series([True] * 3))
    assert m["novos_saturados_obs"] == 1 and m["novos_saturados_prev"] == 2
    assert m["precisao"] == 0.5 and m["recall"] == 1.0
    assert m["acertos_top1000"] == 1


def test_baselines_conservam_total():
    df = pd.DataFrame({"gd_kw": [1.0, 3.0], "gd_add_1a": [0.0, 2.0], "n_uc": [1, 1]})
    for v in modelo.baselines(df, 100.0).values():
        assert abs(v.sum() - 100.0) < 1e-9


def test_custo_reforco_troca_pelo_tamanho_padrao():
    from gdhc import rede
    custo = rede.custo_reforco(gd_kw=[20.0, 5.0, 2000.0], kva=[15.0, 15.0, 1000.0], limite=1.0,
                               tamanhos=[15, 30, 45], custo_kva=100.0, custo_fixo=1000.0)
    # 20 kW em 15 kVA -> troca por 30 kVA; 5 kW não precisa; 2000 kW acima do maior tamanho -> kVA exato
    assert custo.tolist() == [30 * 100 + 1000, 0.0, 2000 * 100 + 1000]


def test_ano_saturacao():
    from gdhc import rede
    anos = rede.ano_saturacao(nivel_atual=[10, 2, 2, 2], taxa_anual=[1, 3, 0, 0.1], capacidade=[10, 10, 10, 10],
                              ano_base=2025, ano_max=2035)
    assert anos[0] == 2025 and anos[1] == 2028 and np.isnan(anos[2]) and np.isnan(anos[3])


def test_painel_point_in_time(tmp_path):
    """Features da origem só veem o snapshot da origem e o anterior; o alvo vem do snapshot origem + h."""
    def snap(ano, ids, gd):
        pd.DataFrame({"trafo_id": ids, "ctmt": "c1", "kva": 10.0, "mun": "m1", "urbano": True,
                      "lat": [-15.0, -15.01], "lon": [-56.0, -56.0], "n_gd": [1, 1], "gd_kw": gd,
                      "n_uc": [5, 5], "consumo_mwh_ano": 10.0, "frac_residencial": 1.0, "ano": ano}) \
            .to_parquet(tmp_path / f"trafos_{ano}.parquet", index=False)
    # IDs mudam a cada ano (como na BDGD); a posição se mantém
    snap(2020, ["a", "b"], [1.0, 2.0])
    snap(2021, ["x", "y"], [3.0, 2.0])
    snap(2023, ["p", "q"], [12.0, 2.0])
    df = P.painel(tmp_path, 2021, 2).set_index("trafo_id")
    assert df.loc["x", "gd_add_1a"] == 2.0 and df.loc["y", "gd_add_1a"] == 0.0
    assert df.loc["x", "gd_add_h"] == 9.0 and df.loc["x", "gd_kw_fut"] == 12.0
    # nada do snapshot de 2023 entra nas features
    assert "gd_kw_fut" not in P.features(tmp_path, 2021).columns
