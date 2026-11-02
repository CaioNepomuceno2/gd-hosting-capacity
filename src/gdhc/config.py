from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    sigla: str
    uf: str
    raw: Path
    interim: Path
    processed: Path
    bdgd_snapshots: dict[int, str]

    @classmethod
    def load(cls, path: str | Path = ROOT / "configs" / "emt.yaml") -> Config:
        cfg = yaml.safe_load(Path(path).read_text())
        p = cfg["paths"]
        out = cls(
            sigla=cfg["distribuidora"]["sigla"],
            uf=cfg["distribuidora"]["uf"],
            raw=ROOT / p["raw"],
            interim=ROOT / p["interim"],
            processed=ROOT / p["processed"],
            bdgd_snapshots={int(k): v for k, v in cfg["bdgd"]["snapshots"].items()},
        )
        for d in (out.raw, out.interim, out.processed):
            d.mkdir(parents=True, exist_ok=True)
        return out


def premissas(path: str | Path = ROOT / "configs" / "premissas.yaml") -> dict:
    return yaml.safe_load(Path(path).read_text())
