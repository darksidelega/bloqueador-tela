"""Detector de nudez: combina NudeNet (partes do corpo) + classificador NSFW.

Para cada região da tela (imagem/vídeo achado ou área em volta de uma
detecção) soma:  prob_nsfw * peso_classificador + Σ max_score(classe) * peso
e bloqueia se passar de limiar_bloqueio.
"""
from collections import OrderedDict

import cv2
import numpy as np

from .. import regioes as rg
from ..config import caminho
from .base import Achado, Detector, usar_gpu
from .modelos import ClassificadorNSFW, NudeNet


class Cache:
    """Guarda resultados por "impressão digital" da imagem: se a fatia não
    mudou desde o último ciclo, não roda o modelo de novo (economiza CPU/GPU)."""

    def __init__(self, tamanho=256):
        self.d = OrderedDict()
        self.tamanho = tamanho
        self.execucoes = 0   # quantas vezes o modelo rodou (p/ medir custo)

    @staticmethod
    def chave(img):
        h, w = img.shape[:2]
        passo = max(1, min(h, w) // 64)  # amostra antes de reduzir (rápido)
        p = cv2.resize(img[::passo, ::passo], (24, 16), interpolation=cv2.INTER_AREA) // 8
        return hash(p.tobytes()) ^ hash(img.shape)

    def pegar(self, img, func):
        k = self.chave(img)
        if k in self.d:
            self.d.move_to_end(k)
            return self.d[k]
        v = func(img)
        self.execucoes += 1
        self.d[k] = v
        if len(self.d) > self.tamanho:
            self.d.popitem(last=False)
        return v


class DetectorNudez(Detector):
    nome = "nudez"

    def __init__(self, cfg):
        self.cfg = cfg
        nc, cc = cfg["nudenet"], cfg["classificador"]
        self.gpu = usar_gpu(cfg)
        if self.gpu:
            modelo, res = caminho(nc["modelo_gpu"]), nc["resolucao_gpu"]
            self.colunas, self.linhas = nc["fatias_colunas"], nc["fatias_linhas"]
            self.max_regioes = cc["max_regioes"]
        else:
            modelo = caminho(nc["modelo_cpu"])
            res = nc["resolucao_cpu"]
            self.colunas, self.linhas = nc["fatias_colunas_cpu"], nc["fatias_linhas_cpu"]
            self.max_regioes = cc["max_regioes_cpu"]
        self.nudenet = NudeNet(modelo, res, self.gpu, nc["score_minimo"])
        self.clf = None
        if cc["ativo"]:
            arq = caminho(cc["modelo_gpu"] if self.gpu else cc["modelo_cpu"])
            self.clf = ClassificadorNSFW(arq, self.gpu)
        self.cache_det = Cache()
        self.cache_clf = Cache()
        self.dispositivo = self.nudenet.sessao.get_providers()[0]

    # ---------- etapa 1: partes do corpo em toda a tela ----------
    def _deteccoes(self, frame):
        H, W = frame.shape[:2]
        fatias = [(0, 0, W, H)] + rg.grade(W, H, self.colunas, self.linhas,
                                           self.cfg["nudenet"]["sobreposicao"])
        dets = []
        for x0, y0, x1, y1 in fatias:
            pedaco = np.ascontiguousarray(frame[y0:y1, x0:x1])
            for c, s, a, b, cc, d in self.cache_det.pegar(pedaco, self.nudenet.detectar):
                dets.append((c, s, a + x0, b + y0, cc + x0, d + y0))
        return dets

    # ---------- etapa 2: regiões a pontuar ----------
    def _regioes(self, frame, imagens, dets):
        H, W = frame.shape[:2]
        pesos = self.cfg["pesos"]
        regs = list(imagens)
        for c, s, x1, y1, x2, y2 in sorted(dets, key=lambda d: -d[1]):
            if pesos.get(c, 0) <= 0:
                continue
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if any(rg.contem(r, cx, cy) for r in regs):
                continue
            # sem imagem achada: usa a área em volta da detecção (contexto)
            w, h = x2 - x1, y2 - y1
            lado = max(w, h) * 1.5
            regs.append((int(max(0, cx - lado)), int(max(0, cy - lado)),
                         int(min(W, cx + lado)), int(min(H, cy + lado))))
        if not regs:
            regs.append((0, 0, W, H))
        return regs

    # ---------- etapa 3: pontuação ----------
    def _pontuar(self, frame, reg, dets, prioridade):
        cfg, pesos = self.cfg, self.cfg["pesos"]
        melhor = {}
        for c, s, x1, y1, x2, y2 in dets:
            if c in pesos and rg.contem(reg, (x1 + x2) / 2, (y1 + y2) / 2):
                melhor[c] = max(melhor.get(c, 0), s)

        termos = {c: s * pesos[c] for c, s in melhor.items() if pesos[c]}
        detalhes = [f"{c} {s:.2f}" for c, s in sorted(melhor.items(), key=lambda t: -t[1])
                    if pesos[c] or c.startswith("FACE")]
        prob = 0.0
        if self.clf and prioridade:
            x1, y1, x2, y2 = reg
            recorte = np.ascontiguousarray(frame[y1:y2, x1:x2])
            if recorte.size:
                prob = self.cache_clf.pegar(recorte, self.clf.prob_nsfw)
                termos["classificador"] = prob * cfg["peso_classificador"]
                detalhes.insert(0, f"NSFW {prob:.2f}")

        if self.clf and prioridade and prob < cfg["veto_classificador"]:
            for c in termos:
                if c != "classificador" and termos[c] > 0:
                    termos[c] *= cfg["fator_veto"]
            detalhes.append("(veto)")

        def s(c):
            return melhor.get(c, 0)

        # genitália/ânus visível = sinal forte, sempre conta
        forte = max(s("FEMALE_GENITALIA_EXPOSED"), s("MALE_GENITALIA_EXPOSED"),
                    s("ANUS_EXPOSED")) >= cfg["score_forte"]
        # contexto masculino (lutador): peito/rosto de homem e nenhum rosto de mulher
        masculino = (max(s("MALE_BREAST_EXPOSED"), s("FACE_MALE")) >= 0.3
                     and s("FACE_FEMALE") < 0.3)
        if masculino and not forte:
            # peitoral grande vira "FEMALE_BREAST" no NudeNet: não conta
            termos.pop("FEMALE_BREAST_EXPOSED", None)
            detalhes.append("(contexto masculino)")

        # classificador sozinho não basta: precisa de algum sinal de corpo feminino
        # ou genitália (o classificador dá 0.95 em telas de UFC sem nada explícito)
        sinais = ["FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED",
                  "BUTTOCKS_EXPOSED", "FACE_FEMALE"]
        if not masculino:
            sinais.append("FEMALE_BREAST_EXPOSED")
        tem_sinal = any(s(c) >= 0.25 for c in sinais)
        if "classificador" in termos and not tem_sinal:
            if termos["classificador"] > cfg["teto_classificador_sozinho"]:
                termos["classificador"] = cfg["teto_classificador_sozinho"]
                detalhes.append("(classificador sozinho: teto)")

        # peito feminino sozinho não basta
        outros = [c for c, v in termos.items()
                  if v > 0 and c not in ("FEMALE_BREAST_EXPOSED", "classificador")]
        peito = termos.get("FEMALE_BREAST_EXPOSED", 0)
        if peito > cfg["teto_peito_sozinho"] and not outros and prob < 0.5:
            termos["FEMALE_BREAST_EXPOSED"] = cfg["teto_peito_sozinho"]
            detalhes.append("(peito sozinho: teto)")

        pontos = sum(termos.values())
        if masculino and not forte and pontos >= cfg["limiar_bloqueio"]:
            pontos = cfg["limiar_bloqueio"] * 0.9
            detalhes.append("(contexto masculino: teto)")
        return pontos, detalhes

    def analisar(self, frame, imagens):
        dets = self._deteccoes(frame)
        regs = self._regioes(frame, imagens, dets)
        pesos = self.cfg["pesos"]

        # classificador só nas regiões mais importantes (com sinais, depois maiores)
        def sinal(r):
            return max([s * pesos.get(c, 0) for c, s, a, b, cc, d in dets
                        if rg.contem(r, (a + cc) / 2, (b + d) / 2)] + [0])
        ordem = sorted(regs, key=lambda r: (-sinal(r), -rg.area(r)))
        achados = []
        for i, reg in enumerate(ordem):
            pontos, detalhes = self._pontuar(frame, reg, dets, i < self.max_regioes)
            if not detalhes:
                continue
            achados.append(Achado(reg, pontos, pontos >= self.cfg["limiar_bloqueio"],
                                  self.nome, detalhes))
        return achados
