"""Downloads dos dados abertos da ANEEL (CKAN): registro de GD e pedidos de conexão de MMGD."""
from __future__ import annotations

import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

CKAN = "https://dadosabertos.aneel.gov.br/api/3/action/package_show"
REGISTRO_GD = ("relacao-de-empreendimentos-de-geracao-distribuida", "empreendimento-geracao-distribuida.parquet")
PEDIDOS_MMGD = ("atendimento-mmgd-mini-e-micro-geracao-distribuida", "pedidos-de-conexao-mmgd-regiao-centro-oeste.parquet")


def baixar(dataset: str, arquivo: str, dest: Path) -> Path:
    """Baixa um recurso do CKAN da ANEEL pelo nome do arquivo; reaproveita se já existir."""
    out = dest / arquivo
    if out.exists():
        return out
    dest.mkdir(parents=True, exist_ok=True)
    recursos = requests.get(CKAN, params={"id": dataset}, timeout=60).json()["result"]["resources"]
    url = next(r["url"] for r in recursos if r["url"].endswith("/" + arquivo))
    log.info("baixando %s", url)
    tmp = out.with_suffix(".part")
    with requests.get(url, stream=True, timeout=1800) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            f.writelines(r.iter_content(1 << 20))
    tmp.replace(out)
    return out
