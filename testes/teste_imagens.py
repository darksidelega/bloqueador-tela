"""Roda o detector em imagens (neutras/lutadores) coladas numa "tela"
sintética: 1) imagem grande; 2) grade de miniaturas tipo Google Imagens.
Uso: python testes/teste_imagens.py pasta_com_imagens [cpu]"""
import glob, os, sys, time
import cv2, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bloqueador import config, regioes
from bloqueador.detectores import criar_detectores

cfg = config.carregar()
if len(sys.argv) > 2: cfg["dispositivo"] = sys.argv[2]
det = criar_detectores(cfg)[0]
print("dispositivo:", det.dispositivo)
imgs = [(os.path.basename(f), cv2.imread(f)) for f in sorted(glob.glob(os.path.join(sys.argv[1], "*.jpg")))]
imgs = [(n, i) for n, i in imgs if i is not None and min(i.shape[:2]) > 100]

def tela_grande(img):
    t = np.full((1080, 1920, 3), 255, np.uint8)
    h, w = img.shape[:2]; s = min(900 / h, 1500 / w)
    r = cv2.resize(img, (int(w * s), int(h * s)))
    t[100:100 + r.shape[0], 200:200 + r.shape[1]] = r
    return t

def tela_grade(lista):
    t = np.full((1080, 1920, 3), 255, np.uint8)
    x, y = 20, 150
    for _, img in lista:
        h, w = img.shape[:2]; s = 200 / h
        r = cv2.resize(img, (int(w * s), 200))[:, :300]
        if x + r.shape[1] > 1900: x, y = 20, y + 215
        if y + 200 > 1080: break
        t[y:y + 200, x:x + r.shape[1]] = r; x += r.shape[1] + 12
    return t

def rodar(nome, tela):
    t0 = time.perf_counter()
    imgs_reg = regioes.regioes_de_imagem(tela)
    ach = det.analisar(tela, imgs_reg)
    ms = (time.perf_counter() - t0) * 1000
    blq = [a for a in ach if a.bloquear]
    print(f"{nome:28s} {ms:6.0f} ms  regioes={len(imgs_reg):2d}  BLOQUEIA={len(blq)}")
    for a in sorted(ach, key=lambda a: -a.pontos)[:3]:
        print(f"    {a.pontos:5.2f} {'X' if a.bloquear else ' '} {a.box} {' | '.join(a.detalhes)}")

for n, i in imgs: rodar(n, tela_grande(i))
rodar("GRADE (todas)", tela_grade(imgs))
det.cache_det.d.clear(); det.cache_clf.d.clear()
rodar("GRADE sem cache", tela_grade(imgs))
rodar("GRADE com cache", tela_grade(imgs))
