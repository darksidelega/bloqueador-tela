"""Modelo para um futuro detector de gore (ainda sem modelo de IA).

Como ativar quando tiver um classificador ONNX de gore:
  1. Coloque o arquivo em modelos/ e ajuste "gore" no config.json:
       "gore": {"modelo": "modelos/gore.onnx", "entrada": 224,
                "indice_classe": 1, "limiar": 0.8}
  2. Em detectores/__init__.py, registre: "gore": DetectorGore
  3. No config.json: "detectores": ["nudez", "gore"]
"""
import cv2
import numpy as np

from ..config import caminho
from .base import Achado, Detector, criar_sessao, usar_gpu


class DetectorGore(Detector):
    nome = "gore"

    def __init__(self, cfg):
        g = cfg.get("gore", {})
        self.limiar = g.get("limiar", 0.8)
        self.entrada = g.get("entrada", 224)
        self.indice = g.get("indice_classe", 1)
        self.sessao = criar_sessao(caminho(g["modelo"]), usar_gpu(cfg))
        self.nome_entrada = self.sessao.get_inputs()[0].name
        self.dispositivo = self.sessao.get_providers()[0]

    def _prob(self, img):
        x = cv2.resize(img, (self.entrada, self.entrada))
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = ((x - 0.5) / 0.5).transpose(2, 0, 1)[None]
        logits = self.sessao.run(None, {self.nome_entrada: x})[0][0]
        e = np.exp(logits - logits.max())
        return float(e[self.indice] / e.sum())

    def analisar(self, frame, regioes):
        H, W = frame.shape[:2]
        achados = []
        for x1, y1, x2, y2 in (regioes or [(0, 0, W, H)]):
            p = self._prob(np.ascontiguousarray(frame[y1:y2, x1:x2]))
            achados.append(Achado((x1, y1, x2, y2), p / self.limiar,
                                  p >= self.limiar, self.nome, [f"GORE {p:.2f}"]))
        return achados
