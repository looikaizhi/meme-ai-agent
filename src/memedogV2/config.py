from __future__ import annotations

import yaml
from pydantic import BaseModel


class V2Config(BaseModel):
    gmgn: dict
    hardfilter: dict


def load_v2_config(path: str) -> V2Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    return V2Config(gmgn=data["gmgn"], hardfilter=data["hardfilter"])
