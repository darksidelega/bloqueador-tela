"""Registro de detectores. Para adicionar gore depois, crie
detectores/gore.py com uma classe DetectorGore(Detector) e inclua aqui."""
from .base import Achado, Detector  # noqa: F401
from .nudez import DetectorNudez

DETECTORES = {
    "nudez": DetectorNudez,
    # "gore": DetectorGore,
}


def criar_detectores(cfg):
    ativos = cfg.get("detectores", ["nudez"])
    return [DETECTORES[n](cfg) for n in ativos if n in DETECTORES]
