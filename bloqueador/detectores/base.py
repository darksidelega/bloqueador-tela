"""Interface comum dos detectores (nudez hoje, gore depois).

Para plugar um novo detector (ex: gore):
  1. Crie uma classe que herde de Detector e implemente analisar().
  2. Registre em detectores/__init__.py (lista DETECTORES).
Cada detector recebe o frame BGR e as regiões de imagem da tela e
devolve uma lista de Achado. O app cobre todo Achado com bloquear=True.
"""
import os
from dataclasses import dataclass, field

import onnxruntime as ort


@dataclass
class Achado:
    box: tuple                 # (x1, y1, x2, y2) em pixels da tela
    pontos: float              # pontuação final (>= limiar => bloqueia)
    bloquear: bool
    origem: str                # nome do detector
    detalhes: list = field(default_factory=list)  # textos p/ o DEBUG


class Detector:
    nome = "base"

    def analisar(self, frame, regioes):
        """frame: np.ndarray BGR (H, W, 3); regioes: lista de (x1,y1,x2,y2)
        com áreas que parecem imagens/vídeos. Retorna lista de Achado."""
        raise NotImplementedError


def gpu_disponivel():
    return "DmlExecutionProvider" in ort.get_available_providers() or \
        "CUDAExecutionProvider" in ort.get_available_providers()


def usar_gpu(cfg):
    disp = cfg.get("dispositivo", "auto")
    return disp != "cpu" and gpu_disponivel()


def criar_sessao(caminho, gpu):
    """Cria sessão ONNX na GPU (CUDA ou DirectML) com fallback para CPU."""
    so = ort.SessionOptions()
    so.log_severity_level = 3
    # sem "espera ativa" das threads: economiza muita CPU entre ciclos
    so.add_session_config_entry("session.intra_op.allow_spinning", "0")
    so.add_session_config_entry("session.inter_op.allow_spinning", "0")
    disponiveis = ort.get_available_providers()
    tentativas = []
    if gpu:
        for p in ("CUDAExecutionProvider", "DmlExecutionProvider"):
            if p in disponiveis:
                tentativas.append([p, "CPUExecutionProvider"])
    # CPU: poucas threads para não pesar o PC
    tentativas.append(["CPUExecutionProvider"])
    erro = None
    for provs in tentativas:
        try:
            if provs == ["CPUExecutionProvider"]:
                so.intra_op_num_threads = max(1, min(4, (os.cpu_count() or 4) // 2))
            else:
                so.intra_op_num_threads = 1  # GPU faz o trabalho pesado
            if "DmlExecutionProvider" in provs:
                so.enable_mem_pattern = False
                so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            return ort.InferenceSession(caminho, so, providers=provs)
        except Exception as e:
            erro = e
    raise RuntimeError(f"Não consegui carregar {caminho}: {erro}")
