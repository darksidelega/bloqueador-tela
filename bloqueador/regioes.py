"""Acha onde estão as imagens/vídeos na tela e monta a grade de fatias."""
import cv2
import numpy as np

ESCALA = 4          # analisa a tela reduzida 4x (rápido)
MIN_LADO = 90       # menor imagem considerada (px da tela)


def grade(W, H, colunas, linhas, sobreposicao):
    """Fatias sobrepostas cobrindo a tela inteira."""
    tw = int(W / colunas * (1 + sobreposicao)) if colunas > 1 else W
    th = int(H / linhas * (1 + sobreposicao)) if linhas > 1 else H
    xs = [0] if colunas == 1 else np.linspace(0, W - tw, colunas).astype(int)
    ys = [0] if linhas == 1 else np.linspace(0, H - th, linhas).astype(int)
    return [(int(x), int(y), int(x) + tw, int(y) + th) for y in ys for x in xs]


def regioes_de_imagem(frame, maximo=12):
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
    saida = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if w * ESCALA < MIN_LADO or h * ESCALA < MIN_LADO:
            continue
        if area / float(w * h) < 0.55:      # forma muito vazada (texto, bordas)
            continue
        if cinza[y:y + h, x:x + w].std() < 12:   # bloco liso (botão, barra)
            continue
        saida.append((area, (x * ESCALA, y * ESCALA,
                             min(W, (x + w) * ESCALA), min(H, (y + h) * ESCALA))))
    saida.sort(reverse=True)
    return [b for _, b in saida[:maximo]]


def contem(caixa, x, y):
    x1, y1, x2, y2 = caixa
    return x1 <= x <= x2 and y1 <= y <= y2


def area(c):
    return max(0, c[2] - c[0]) * max(0, c[3] - c[1])
