"""Carrega o config.json (cria com os padrões se não existir)."""
import copy
import json
import os
import sys

if getattr(sys, "frozen", False):
    PASTA = os.path.dirname(sys.executable)
else:
    PASTA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CAMINHO = os.path.join(PASTA, "config.json")

PADRAO = {
    "debug": True,
    "modo": "tela",              # "tela" = cobre tudo | "parte" = só a área
    "intervalo": 0.15,           # segundos mínimos entre análises
    "persistencia": 1.0,         # segundos mantendo o mosaico após sumir
    "margem": 0.30,
    "bloco": 14,
    "bloco_tela": 45,
    "dispositivo": "auto",       # "auto" (GPU se houver) | "gpu" | "cpu"
    "detectores": ["nudez"],     # futuramente: ["nudez", "gore"]

    "nudenet": {
        "modelo_gpu": "modelos/640m.onnx",
        "resolucao_gpu": 640,
        "modelo_cpu": "modelos/320n.onnx",
        "resolucao_cpu": 320,
        "fatias_colunas": 3,     # grade de fatias (acha imagens pequenas)
        "fatias_linhas": 2,
        "fatias_colunas_cpu": 2,
        "fatias_linhas_cpu": 2,
        "sobreposicao": 0.2,
        "score_minimo": 0.20     # abaixo disso a detecção é ignorada
    },
    "classificador": {
        "ativo": True,
        "modelo_gpu": "modelos/nsfw_vit.onnx",
        "modelo_cpu": "modelos/nsfw_vit_int8.onnx",
        "max_regioes": 10,
        "max_regioes_cpu": 2
    },

    # Pontuação: cada região soma score*peso (maior score de cada classe)
    # e o score do classificador * peso_classificador. Bloqueia se >= limiar.
    "limiar_bloqueio": 1.0,
    "peso_classificador": 1.15,
    "pesos": {
        "FEMALE_GENITALIA_EXPOSED": 4.0,
        "MALE_GENITALIA_EXPOSED": 3.0,
        "ANUS_EXPOSED": 3.5,
        "FEMALE_BREAST_EXPOSED": 1.1,
        "BUTTOCKS_EXPOSED": 1.0,
        "FEMALE_GENITALIA_COVERED": 0.8,
        "ANUS_COVERED": 0.6,
        "FEMALE_BREAST_COVERED": 0.25,
        "BUTTOCKS_COVERED": 0.25,
        "BELLY_EXPOSED": 0.15,
        "MALE_BREAST_EXPOSED": -0.6,
        "FACE_MALE": 0.0,
        "FACE_FEMALE": 0.0
    },
    # Peito feminino sozinho (sem classificador/outro sinal) só conta até isso.
    # Evita bloquear lutador sem camisa confundido com peito feminino.
    "teto_peito_sozinho": 0.85,
    # Se o classificador tiver certeza que é imagem normal (prob < veto),
    # os pontos do NudeNet são multiplicados por fator_veto (menos falso positivo).
    "veto_classificador": 0.02,
    "fator_veto": 0.6,

    "palavras_titulo": [
        "porn", "pornô", "porno", "xxx", "xvideos", "xnxx", "xhamster",
        "redtube", "youporn", "hentai", "nsfw", "onlyfans", "putaria",
        "brazzers", "chaturbate", "nudes", "sexo explícito", "rule34"
    ],
    "ocr": {
        "ativo": False,
        "intervalo": 2.0
    },
    "sites_bloqueados": "sites_bloqueados.txt"
}


def _mesclar(base, novo):
    for k, v in novo.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _mesclar(base[k], v)
        else:
            base[k] = v
    return base


def carregar():
    cfg = copy.deepcopy(PADRAO)
    if os.path.isfile(CAMINHO):
        with open(CAMINHO, encoding="utf-8") as f:
            _mesclar(cfg, json.load(f))
    else:
        with open(CAMINHO, "w", encoding="utf-8") as f:
            json.dump(PADRAO, f, ensure_ascii=False, indent=2)
    return cfg


def caminho(rel):
    """Resolve caminho relativo à pasta do app."""
    return rel if os.path.isabs(rel) else os.path.join(PASTA, rel)
