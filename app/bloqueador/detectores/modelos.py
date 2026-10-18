"""Wrappers dos modelos ONNX: NudeNet (partes do corpo) e classificador NSFW."""
import cv2
import numpy as np

from .base import criar_sessao

CLASSES_NUDENET = [
    "FEMALE_GENITALIA_COVERED", "FACE_FEMALE", "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_EXPOSED", "FEMALE_GENITALIA_EXPOSED", "MALE_BREAST_EXPOSED",
    "ANUS_EXPOSED", "FEET_EXPOSED", "BELLY_COVERED", "FEET_COVERED",
    "ARMPITS_COVERED", "ARMPITS_EXPOSED", "FACE_MALE", "BELLY_EXPOSED",
    "MALE_GENITALIA_EXPOSED", "ANUS_COVERED", "FEMALE_BREAST_COVERED",
    "BUTTOCKS_COVERED",
]


class NudeNet:
    """Detector de partes do corpo (YOLOv8). Pós-processamento vetorizado
    (o do pacote nudenet usa um loop Python lento no modelo 640)."""

    def __init__(self, caminho, resolucao, gpu, score_minimo=0.2):
        self.sessao = criar_sessao(caminho, gpu)
        self.entrada = self.sessao.get_inputs()[0].name
        self.res = resolucao
        self.score_minimo = score_minimo

    def detectar(self, img):
        """img BGR. Retorna lista de (classe, score, x1, y1, x2, y2)."""
        h, w = img.shape[:2]
        lado = max(h, w)
        quadrado = np.zeros((lado, lado, 3), np.uint8)
        quadrado[:h, :w] = img
        blob = cv2.dnn.blobFromImage(quadrado, 1 / 255.0, (self.res, self.res),
                                     swapRB=True, crop=False)
        saida = self.sessao.run(None, {self.entrada: blob})[0][0].T  # (N, 22)
        scores = saida[:, 4:]
        ids = scores.argmax(1)
        melhores = scores[np.arange(len(ids)), ids]
        ok = melhores >= self.score_minimo
        if not ok.any():
            return []
        cx, cy, bw, bh = (saida[ok, :4] * (lado / self.res)).T
        ids, melhores = ids[ok], melhores[ok]
        caixas = np.stack([cx - bw / 2, cy - bh / 2, bw, bh], 1)
        idx = cv2.dnn.NMSBoxes(caixas.tolist(), melhores.tolist(),
                               self.score_minimo, 0.45)
        res = []
        for i in np.array(idx).flatten():
            x, y, bw_, bh_ = caixas[i]
            x1, y1 = max(0, x), max(0, y)
            x2, y2 = min(w, x + bw_), min(h, y + bh_)
            if x2 > x1 and y2 > y1:
                res.append((CLASSES_NUDENET[ids[i]], float(melhores[i]),
                            int(x1), int(y1), int(x2), int(y2)))
        return res


class ClassificadorNSFW:
    """ViT (Falconsai/nsfw_image_detection, ONNX): imagem -> prob. de NSFW.
    Pega casos que o detector de partes perde (mão cobrindo, sem rosto)."""

    def __init__(self, caminho, gpu):
        self.sessao = criar_sessao(caminho, gpu)
        self.entrada = self.sessao.get_inputs()[0].name

    def prob_nsfw(self, img):
        x = cv2.resize(img, (224, 224), interpolation=cv2.INTER_LINEAR)
        x = cv2.cvtColor(x, cv2.COLOR_BGR2RGB).astype(np.float32)
        x = (x / 255.0 - 0.5) / 0.5
        x = x.transpose(2, 0, 1)[None]
        logits = self.sessao.run(None, {self.entrada: x})[0][0]
        e = np.exp(logits - logits.max())
        return float(e[1] / e.sum())
