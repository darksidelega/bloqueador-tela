"""Mede a IA com duas pastas suas: uma de conteúdo adulto e uma normal.
Cada foto é testada sozinha (como no app Fotos) e numa grade de miniaturas
(como no Google Imagens). Mostra só o nome do arquivo e a nota: nenhuma
imagem é aberta, copiada nem enviada.

Uso: python testes/teste_pastas.py pasta_adulto pasta_normal [cpu]"""
import glob
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bloqueador import config, regioes  # noqa: E402
from bloqueador.detectores import criar_detectores  # noqa: E402

EXTENSOES = ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp")


def carregar(pasta):
    arquivos = sorted(f for e in EXTENSOES for f in glob.glob(os.path.join(pasta, "**", e),
                                                               recursive=True))
    imgs = []
    for f in arquivos:
        img = cv2.imdecode(np.fromfile(f, np.uint8), cv2.IMREAD_COLOR)  # aceita acento no nome
        if img is not None and min(img.shape[:2]) >= 64:
            imgs.append((os.path.relpath(f, pasta), img))
    return imgs


def tela_sozinha(img):
    """Foto grande no meio da tela, como num visualizador."""
    t = np.full((1080, 1920, 3), 32, np.uint8)
    h, w = img.shape[:2]
    s = min(900 / h, 1500 / w)
    r = cv2.resize(img, (int(w * s), int(h * s)))
    y, x = (1080 - r.shape[0]) // 2, (1920 - r.shape[1]) // 2
    t[y:y + r.shape[0], x:x + r.shape[1]] = r
    return t, (x, y, x + r.shape[1], y + r.shape[0])


def tela_grade(lista):
    """Miniaturas de 200 px de altura, como no Google Imagens."""
    t = np.full((1080, 1920, 3), 255, np.uint8)
    x, y, caixas = 20, 150, []
    for nome, img in lista:
        h, w = img.shape[:2]
        r = cv2.resize(img, (int(w * 200 / h), 200))[:, :300]
        if x + r.shape[1] > 1900:
            x, y = 20, y + 215
        if y + 200 > 1080:
            break
        t[y:y + 200, x:x + r.shape[1]] = r
        caixas.append((nome, (x, y, x + r.shape[1], y + 200)))
        x += r.shape[1] + 10
    return t, caixas


def nota_em(achados, caixa):
    """Maior nota de um achado cujo centro cai na caixa, e se bloqueou."""
    x1, y1, x2, y2 = caixa
    dentro = [a for a in achados
              if x1 <= (a.box[0] + a.box[2]) / 2 < x2 and y1 <= (a.box[1] + a.box[3]) / 2 < y2]
    if not dentro:
        return 0.0, False, ""
    a = max(dentro, key=lambda a: a.pontos)
    return a.pontos, any(d.bloquear for d in dentro), " | ".join(a.detalhes)


def rodar(det, imgs):
    """{nome: (nota sozinha, bloqueou sozinha, nota grade, bloqueou grade, detalhes)}"""
    res = {}
    for nome, img in imgs:
        tela, caixa = tela_sozinha(img)
        p, b, d = nota_em(det.analisar(tela, regioes.regioes_de_imagem(tela)), caixa)
        res[nome] = [p, b, 0.0, False, d]
    for i in range(0, len(imgs), 24):
        tela, caixas = tela_grade(imgs[i:i + 24])
        achados = det.analisar(tela, regioes.regioes_de_imagem(tela))
        for nome, caixa in caixas:
            p, b, _ = nota_em(achados, caixa)
            res[nome][2:4] = [p, b]
    return res


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    cfg = config.carregar()
    if len(sys.argv) > 3:
        cfg["dispositivo"] = sys.argv[3]
    det = criar_detectores(cfg)[0]
    print("dispositivo:", det.dispositivo, "| limiar:", cfg["limiar_bloqueio"])
    for rotulo, pasta, deve in (("ADULTO", sys.argv[1], True), ("NORMAL", sys.argv[2], False)):
        imgs = carregar(pasta)
        res = rodar(det, imgs)
        print(f"\n===== {rotulo}: {len(imgs)} imagens (deveria {'bloquear' if deve else 'liberar'}) =====")
        erros_s = erros_g = 0
        for nome, (ps, bs, pg, bg, det_txt) in sorted(res.items(), key=lambda t: t[1][0]):
            erro_s, erro_g = bs != deve, bg != deve
            erros_s += erro_s
            erros_g += erro_g
            if erro_s or erro_g:
                onde = ("sozinha" if erro_s else "") + (" e " if erro_s and erro_g else "") \
                    + ("na grade" if erro_g else "")
                print(f"  ERRO ({onde}) {nome}: sozinha {ps:.2f}, grade {pg:.2f} | {det_txt}")
        n = max(1, len(imgs))
        print(f"  acertos: sozinha {100 - 100 * erros_s / n:.0f}% | grade {100 - 100 * erros_g / n:.0f}%")


if __name__ == "__main__":
    main()
