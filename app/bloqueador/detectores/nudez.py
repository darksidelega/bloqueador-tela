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


# classes em que uma detecção fraca (pouca confiança) deve pesar pouco:
# abaixo de 0.5 a contribuição cai por uma curva quadrática (0.3 vira ~0.18,
# 0.2 vira ~0.08). Acima de 0.5 conta normal. Rosto e barriga ficam de fora.
_CLASSES_RAMPA = {"FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED",
                  "FEMALE_GENITALIA_COVERED", "ANUS_COVERED", "BUTTOCKS_EXPOSED",
                  "FEMALE_BREAST_EXPOSED"}


def _efetivo(classe, score):
    if classe in _CLASSES_RAMPA and score < 0.5:
        return score * score / 0.5
    return score


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
        """Lista de (região, soma_deteccoes). Região grande (vídeo em tela
        cheia, grade que não separou) não soma detecções de pontos distantes:
        cada detecção vira uma região local com seu contexto."""
        H, W = frame.shape[:2]
        pesos = self.cfg["pesos"]
        limite = self.cfg["regiao_grande"] * W * H
        pequenas = [r for r in imagens if rg.area(r) <= limite]
        regs = [(r, True) for r in pequenas] +                [(r, False) for r in imagens if rg.area(r) > limite]
        locais = []
        for c, s, x1, y1, x2, y2 in sorted(dets, key=lambda d: -d[1]):
            if pesos.get(c, 0) <= 0:
                continue
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            if any(rg.contem(r, cx, cy) for r in pequenas + locais):
                continue
            # área em volta da detecção + o corpo da mesma pessoa (cobre a
            # pessoa toda, não só o seio)
            lado = max(x2 - x1, y2 - y1) * 2.0
            bx1, by1, bx2, by2 = self._corpo(dets, (x1, y1, x2, y2), pequenas, limite)
            locais.append((int(max(0, min(cx - lado, bx1))), int(max(0, min(cy - lado, by1))),
                           int(min(W, max(cx + lado, bx2))), int(min(H, max(cy + lado, by2)))))
        regs += [(r, True) for r in locais]
        if not regs:
            regs.append(((0, 0, W, H), False))
        return regs

    @staticmethod
    def _corpo(dets, caixa, pequenas, limite):
        """Junta à `caixa` as partes do corpo vizinhas (rosto, barriga,
        pernas...) que não estão em outra imagem, até `limite` de área.
        Retorna a caixa da pessoa com uma folga."""
        x1, y1, x2, y2 = caixa
        juntou = True
        while juntou:
            juntou = False
            alc = max(x2 - x1, y2 - y1) * 0.8
            for _, _, a, b, c, d in dets:
                mx, my = (a + c) / 2, (b + d) / 2
                if a >= x1 and b >= y1 and c <= x2 and d <= y2:
                    continue  # já está dentro
                if not (x1 - alc <= mx <= x2 + alc and y1 - alc <= my <= y2 + alc):
                    continue
                if any(rg.contem(r, mx, my) for r in pequenas):
                    continue  # é de outra imagem (miniatura vizinha)
                n = (min(x1, a), min(y1, b), max(x2, c), max(y2, d))
                if rg.area(n) > limite:
                    continue
                (x1, y1, x2, y2), juntou = n, True
        folga = max(x2 - x1, y2 - y1) * 0.15
        return x1 - folga, y1 - folga, x2 + folga, y2 + folga

    # ---------- etapa 3: pontuação ----------
    def _pontuar(self, frame, reg, dets, prioridade, somar=True):
        cfg, pesos = self.cfg, self.cfg["pesos"]
        melhor = {}
        for c, s, x1, y1, x2, y2 in (dets if somar else []):
            if c in pesos and rg.contem(reg, (x1 + x2) / 2, (y1 + y2) / 2):
                melhor[c] = max(melhor.get(c, 0), s)

        # detecção fraca (abaixo de 0.5) nas classes de peso alto conta bem menos:
        # o NudeNet marca "genitália/peito" em 0.2-0.4 em roupa, manequim, etc.,
        # e com peso cheio isso sozinho já bloqueava (falso positivo).
        termos = {c: _efetivo(c, s) * pesos[c] for c, s in melhor.items() if pesos[c]}
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

        # imagem claramente masculina (lutador sem camisa): o rosto masculino
        # domina o feminino E o peito lido como masculino domina o "feminino"
        # (o peitoral vira FEMALE_BREAST no NudeNet). Vale mesmo com um rosto
        # feminino fraco junto, que o modelo erra nesses casos.
        male_face, fem_face = s("FACE_MALE"), s("FACE_FEMALE")
        male_peito, fem_peito = s("MALE_BREAST_EXPOSED"), s("FEMALE_BREAST_EXPOSED")
        # sinais de homem sem camisa: peito masculino exposto (o peitoral às
        # vezes é lido como feminino, por isso basta ele existir), ou rosto
        # masculino sem rosto/peito feminino competindo (lutador de shorts).
        masc_sinais = (male_peito >= 0.4
                       or (male_face >= 0.4 and fem_face < 0.4 and fem_peito < 0.5))
        # genitália/ânus visível = sinal forte, atropela o contexto masculino.
        # Numa imagem masculina a "genitália feminina" quase sempre é erro, então
        # ela precisa de confiança bem maior para contar.
        forte = (max(s("MALE_GENITALIA_EXPOSED"), s("ANUS_EXPOSED")) >= cfg["score_forte"]
                 or s("FEMALE_GENITALIA_EXPOSED") >= (0.6 if masc_sinais else cfg["score_forte"]))
        masculino = masc_sinais and not forte
        if masculino:
            # peitoral e "genitália/peito feminino" são erros sobre o corpo do homem
            for c in ("FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED",
                      "FEMALE_GENITALIA_COVERED"):
                termos.pop(c, None)
            detalhes.append("(contexto masculino)")

        # classificador sozinho não basta: precisa de algum sinal de corpo feminino
        # ou genitália (o classificador dá 0.95 em telas de UFC sem nada explícito)
        sinais = ["FEMALE_GENITALIA_EXPOSED", "MALE_GENITALIA_EXPOSED", "ANUS_EXPOSED",
                  "BUTTOCKS_EXPOSED", "FACE_FEMALE"]
        if not masculino:
            # barriga de fora + classificador certo = nua tapando o peito com a mão
            sinais += ["FEMALE_BREAST_EXPOSED", "BELLY_EXPOSED"]
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
        # classificador com certeza que é limpo (prob ~0): só genitália/ânus
        # MUITO confiante (>= 0.8) mantém o bloqueio. Produto, manequim e roupa
        # dão "genitália" fraca que, sem o classificador, virava falso positivo.
        if (self.clf and prioridade and prob < cfg["veto_classificador"]
                and max(s("FEMALE_GENITALIA_EXPOSED"), s("MALE_GENITALIA_EXPOSED"),
                        s("ANUS_EXPOSED")) < 0.8 and pontos >= cfg["limiar_bloqueio"]):
            pontos = cfg["limiar_bloqueio"] * 0.9
            detalhes.append("(classificador certo que é normal)")
        return pontos, detalhes

    def analisar(self, frame, imagens):
        dets = self._deteccoes(frame)
        regs = self._regioes(frame, imagens, dets)
        pesos = self.cfg["pesos"]

        # classificador só nas regiões mais importantes (com sinais, depois maiores)
        def sinal(r):
            reg, somar = r
            return max([s * pesos.get(c, 0) for c, s, a, b, cc, d in dets
                        if somar and rg.contem(reg, (a + cc) / 2, (b + d) / 2)] + [0])
        ordem = sorted(regs, key=lambda r: (-sinal(r), -rg.area(r[0])))
        achados = []
        for i, (reg, somar) in enumerate(ordem):
            pontos, detalhes = self._pontuar(frame, reg, dets, i < self.max_regioes, somar)
            if not detalhes:
                continue
            achados.append(Achado(reg, pontos, pontos >= self.cfg["limiar_bloqueio"],
                                  self.nome, detalhes))
        return achados
