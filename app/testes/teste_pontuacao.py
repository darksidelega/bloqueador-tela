"""Testa as regras de pontuação com detecções sintéticas (sem imagens/modelos).
Uso: python testes/teste_pontuacao.py"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bloqueador import config  # noqa: E402
from bloqueador.detectores.nudez import Cache, DetectorNudez  # noqa: E402


class ClfFalso:
    def __init__(self, p):
        self.p = p

    def prob_nsfw(self, _):
        return self.p


def pontuar(nsfw, **classes):
    d = DetectorNudez.__new__(DetectorNudez)
    d.cfg = config.PADRAO
    d.clf = ClfFalso(nsfw)
    d.cache_clf = Cache()
    dets = [(c, s, 10, 10, 50, 50) for c, s in classes.items()]
    return d._pontuar(np.full((100, 100, 3), 7, np.uint8), (0, 0, 100, 100), dets, True)


CASOS = [  # (descrição, deve bloquear, nsfw, classes)
    ("lutador: peitoral vira peito feminino", False, 0.95,
     dict(FACE_MALE=0.6, MALE_BREAST_EXPOSED=0.5, FEMALE_BREAST_EXPOSED=0.6)),
    ("lutador sem rosto, só peitoral", False, 0.97,
     dict(MALE_BREAST_EXPOSED=0.4, FEMALE_BREAST_EXPOSED=0.55, BELLY_EXPOSED=0.8)),
    ("tela de UFC: só classificador", False, 0.97, {}),
    ("lutador de shorts", False, 0.9,
     dict(FACE_MALE=0.5, FEMALE_GENITALIA_COVERED=0.5, BELLY_EXPOSED=0.7)),
    ("peito masculino, classificador normal", False, 0.0,
     dict(FEMALE_BREAST_EXPOSED=0.7)),
    ("pornô: mão cobrindo, rosto feminino", True, 0.95, dict(FACE_FEMALE=0.5)),
    ("pornô: sem rosto, nádega", True, 0.9, dict(BUTTOCKS_EXPOSED=0.5)),
    ("topless", True, 0.8, dict(FEMALE_BREAST_EXPOSED=0.6, FACE_FEMALE=0.5)),
    ("casal", True, 0.9, dict(FACE_MALE=0.6, FACE_FEMALE=0.5, FEMALE_BREAST_EXPOSED=0.6)),
    ("pênis com rosto masculino", True, 0.9, dict(FACE_MALE=0.6, MALE_GENITALIA_EXPOSED=0.6)),
    ("genitália feminina, classificador incerto", True, 0.5,
     dict(FEMALE_GENITALIA_EXPOSED=0.3)),
]

erros = 0
for desc, esperado, nsfw, classes in CASOS:
    pontos, detalhes = pontuar(nsfw, **classes)
    ok = (pontos >= config.PADRAO["limiar_bloqueio"]) == esperado
    erros += not ok
    print(f"{'ok  ' if ok else 'ERRO'} {pontos:5.2f} {'bloqueia' if esperado else 'libera  '} "
          f"{desc} | {' | '.join(detalhes)}")
print("TUDO OK" if not erros else f"{erros} ERRO(S)")
sys.exit(bool(erros))
