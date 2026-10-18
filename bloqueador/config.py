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
    "modo": "parte",             # "parte" = só a área | "tela" = cobre tudo
    "intervalo": 0.25,           # segundos entre análises (normal)
    "intervalo_rapido": 0.10,    # quando algo suspeito aparece
    "persistencia": 1.0,         # segundos mantendo o mosaico após sumir
    "margem": 0.50,              # aumenta a área coberta (0.5 = +25% de cada lado)
    "suavizar_px": 48,           # borda suave em volta do mosaico (feather)
    "bloco": 14,
    "bloco_tela": 45,
    # No blur de tela inteira, deixa livres a faixa de cima da janela ativa
    # (abas + botões de fechar, em px a 100% de escala) e a barra de tarefas.
    "faixa_livre_px": 90,
    "liberar_barra_tarefas": True,
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
    # Classificador sem nenhum sinal de corpo (rosto feminino, peito, nádega,
    # genitália) só conta até isso -> sozinho não bloqueia (telas de UFC).
    "teto_classificador_sozinho": 0.6,
    # Score a partir do qual genitália/ânus visível ignora o contexto masculino.
    "score_forte": 0.4,
    # Região maior que essa fração da tela não soma detecções de pontos
    # diferentes (evita juntar várias miniaturas e borrar tudo).
    "regiao_grande": 0.3,
    "fator_veto": 0.6,

    "palavras_titulo": [
        "porn", "pornô", "porno", "xxx", "xvideos", "xnxx", "xhamster",
        "redtube", "youporn", "hentai", "nsfw", "onlyfans", "putaria",
        "brazzers", "chaturbate", "nudes", "sexo explícito", "rule34"
    ],
    "ocr": {
        "ativo": True,           # lê o texto da tela (OCR do Windows, local)
        "intervalo": 2.0,
        "persistencia": 4.0,     # segundos cobrindo depois de ver a palavra
        "palavras": [
            "porn", "pornô", "porno", "pornhub", "xvideos", "xnxx", "xhamster",
            "redtube", "youporn", "hentai", "brazzers", "onlyfans", "chaturbate",
            "spankbang", "rule34", "nhentai"
        ]
    },
    # Título e OCR só valem quando a janela ativa é um navegador
    # (mensagem com a palavra no WhatsApp/Discord app não bloqueia).
    "so_navegador": True,
    "navegadores": [
        "chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe",
        "opera_gx.exe", "vivaldi.exe", "arc.exe", "zen.exe", "librewolf.exe",
        "waterfox.exe", "iexplore.exe", "browser.exe", "chromium.exe", "thorium.exe"
    ],
    # Janelas onde título e OCR não bloqueiam (você editando listas/logs,
    # terminal, Claude). A detecção de imagens continua valendo nelas.
    "ignorar_janelas": [
        "claude", "windows terminal", "terminal", "powershell", "prompt de comando",
        "cmd.exe", "python", "visual studio code", "bloco de notas", "notepad",
        "bloqueador.log", "sites_bloqueados", "config.json", "bloqueador-tela"
    ],
    "sites_bloqueados": "sites_bloqueados.txt",
    "forcar_safesearch": True    # Google/Bing/DuckDuckGo sempre com SafeSearch
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
