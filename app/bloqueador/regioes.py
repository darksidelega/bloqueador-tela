"""Acha onde estão as imagens/vídeos na tela e monta a grade de fatias."""
import cv2
import numpy as np

ESCALA = 2          # analisa a tela reduzida 2x (separa bem as miniaturas)
MIN_LADO = 90       # menor imagem considerada (px da tela)


def grade(W, H, colunas, linhas, sobreposicao):
    """Fatias sobrepostas cobrindo a tela inteira."""
    tw = int(W / colunas * (1 + sobreposicao)) if colunas > 1 else W
    th = int(H / linhas * (1 + sobreposicao)) if linhas > 1 else H
    xs = [0] if colunas == 1 else np.linspace(0, W - tw, colunas).astype(int)
    ys = [0] if linhas == 1 else np.linspace(0, H - th, linhas).astype(int)
    return [(int(x), int(y), int(x) + tw, int(y) + th) for y in ys for x in xs]


def regioes_de_imagem(frame, maximo=40):
    """Retângulos que parecem fotos/vídeos (muitas cores, área preenchida),
    separados do fundo da página. Ex: miniaturas do Google Imagens."""
    H, W = frame.shape[:2]
    p = cv2.resize(frame, (W // ESCALA, H // ESCALA), interpolation=cv2.INTER_AREA)
    # cor de fundo = cor mais comum (quantizada)
    q = (p // 16).reshape(-1, 3).astype(np.int32)
    cod = q[:, 0] * 256 + q[:, 1] * 16 + q[:, 2]
    fundo = np.bincount(cod).argmax()
    fora_fundo = (cod != fundo).reshape(p.shape[:2]).astype(np.uint8)
    # textura: foto tem variação contínua; texto/ícone é fino e esparso
    cinza = cv2.cvtColor(p, cv2.COLOR_BGR2GRAY)
    mascara = cv2.morphologyEx(fora_fundo, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, rot, stats, _ = cv2.connectedComponentsWithStats(mascara, 8)
    caixas = []
    for i in range(1, n):
        x, y, w, h, _ = stats[i]
        caixas += _cortar(fora_fundo, x, y, x + w, y + h)
    saida = []
    for x1, y1, x2, y2 in caixas:
        w, h = x2 - x1, y2 - y1
        if w * ESCALA < MIN_LADO or h * ESCALA < MIN_LADO:
            continue
        area = int(fora_fundo[y1:y2, x1:x2].sum())
        if area / float(w * h) < 0.55:      # forma muito vazada (texto, bordas)
            continue
        if cinza[y1:y2, x1:x2].std() < 12:  # bloco liso (botão, barra)
            continue
        saida.append((area, (x1 * ESCALA, y1 * ESCALA,
                             min(W, x2 * ESCALA), min(H, y2 * ESCALA))))
    saida.sort(reverse=True)
    return [b for _, b in saida[:maximo]]


def _cortar(m, x1, y1, x2, y2, prof=0):
    """Corte XY: divide um bloco onde há "corredores" de fundo (linhas ou
    colunas quase vazias), separando cada miniatura de uma grade."""
    if prof > 6 or x2 - x1 < 8 or y2 - y1 < 8:
        return [(x1, y1, x2, y2)]
    bloco = m[y1:y2, x1:x2]
    for eixo in (0, 1):                      # 0: colunas, 1: linhas
        cheio = bloco.mean(axis=eixo) > 0.12
        if cheio.all() or not cheio.any():
            continue
        pedacos, ini = [], None
        for i, v in enumerate(cheio):
            if v and ini is None:
                ini = i
            elif not v and ini is not None:
                pedacos.append((ini, i))
                ini = None
        if ini is not None:
            pedacos.append((ini, len(cheio)))
        if len(pedacos) < 2:
            # só aparou a borda vazia
            a, b = pedacos[0]
            if eixo == 0:
                return _cortar(m, x1 + a, y1, x1 + b, y2, prof + 1)
            return _cortar(m, x1, y1 + a, x2, y1 + b, prof + 1)
        saida = []
        for a, b in pedacos:
            if eixo == 0:
                saida += _cortar(m, x1 + a, y1, x1 + b, y2, prof + 1)
            else:
                saida += _cortar(m, x1, y1 + a, x2, y1 + b, prof + 1)
        return saida
    return [(x1, y1, x2, y2)]


def contem(caixa, x, y):
    x1, y1, x2, y2 = caixa
    return x1 <= x <= x2 and y1 <= y <= y2


def area(c):
    return max(0, c[2] - c[0]) * max(0, c[3] - c[1])
