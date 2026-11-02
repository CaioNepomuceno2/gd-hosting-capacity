"""Baixa o registro de empreendimentos de GD e os pedidos de conexão de MMGD (Centro-Oeste) da ANEEL."""
import logging

import duckdb

from gdhc import aneel
from gdhc.config import Config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
cfg = Config.load()
reg = aneel.baixar(*aneel.REGISTRO_GD, cfg.raw)
ped = aneel.baixar(*aneel.PEDIDOS_MMGD, cfg.raw)

# registro de GD da UF: potência por código CEG (usada para corrigir potências implausíveis da BDGD)
duckdb.sql(f"""
    copy (select CodEmpreendimento as ceg, SigAgente as agente, MdaPotenciaInstaladaKW as kw,
                 DscPorte as porte, SigTipoGeracao as tipo, CodMunicipioIbge as mun_ibge,
                 DthAtualizaCadastralEmpreend as data_cadastro
          from read_parquet('{reg}') where SigUF = '{cfg.uf}')
    to '{cfg.interim / "registro_gd.parquet"}' (format parquet)
""")
# nomes dos municípios (IBGE) para os relatórios
duckdb.sql(f"""
    copy (select distinct CodMunicipioIbge::varchar as mun, NomMunicipio as municipio
          from read_parquet('{reg}') where SigUF = '{cfg.uf}')
    to '{cfg.interim / "municipios.parquet"}' (format parquet)
""")
# pedidos de conexão: só o retrato mais recente de cada pedido da distribuidora
duckdb.sql(f"""
    copy (select * from read_parquet('{ped}')
          where SigAgenteDistribuicao = 'Energisa {cfg.uf}'
            and DatPrzEnvio = (select max(DatPrzEnvio) from read_parquet('{ped}')
                               where SigAgenteDistribuicao = 'Energisa {cfg.uf}'))
    to '{cfg.interim / "pedidos_mmgd.parquet"}' (format parquet)
""")
print(duckdb.sql(f"select count(*) from '{cfg.interim / 'registro_gd.parquet'}'").fetchall(),
      duckdb.sql(f"select count(*) from '{cfg.interim / 'pedidos_mmgd.parquet'}'").fetchall())
