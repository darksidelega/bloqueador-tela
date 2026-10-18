"""Instalação: baixa os modelos de IA, cria o config, liga o início com o
Windows e inicia o bloqueador. Depois disso tudo roda offline; nenhuma
imagem da tela sai do PC."""
import os
import sys
import urllib.request

from bloqueador import config, protecao

MODELOS = {
    # NudeNet v3.4 (via API do GitHub; o link direto pede login)
    "640m.onnx": ("https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176832019",
                  {"Accept": "application/octet-stream"}),
    "320n.onnx": ("https://api.github.com/repos/notAI-tech/NudeNet/releases/assets/176831997",
                  {"Accept": "application/octet-stream"}),
    # Classificador NSFW (Falconsai/nsfw_image_detection em ONNX)
    "nsfw_vit.onnx": ("https://huggingface.co/onnx-community/nsfw_image_detection-ONNX"
                      "/resolve/main/onnx/model.onnx", {}),
    "nsfw_vit_int8.onnx": ("https://huggingface.co/onnx-community/nsfw_image_detection-ONNX"
                           "/resolve/main/onnx/model_quantized.onnx", {}),
}


def baixar(nome, url, cabecalhos):
    destino = config.caminho(os.path.join("modelos", nome))
    if os.path.isfile(destino) and os.path.getsize(destino) > 1_000_000:
        print(f"  {nome}: já existe")
        return
    print(f"  {nome}: baixando...", end="", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "bloqueador-tela", **cabecalhos})
    with urllib.request.urlopen(req) as r, open(destino + ".part", "wb") as f:
        while bloco := r.read(1 << 20):
            f.write(bloco)
    if os.path.getsize(destino + ".part") < 1_000_000:
        os.remove(destino + ".part")
        raise RuntimeError(f"download de {nome} veio vazio/errado")
    os.replace(destino + ".part", destino)
    print(f" ok ({os.path.getsize(destino) // 1_000_000} MB)")


if __name__ == "__main__":
    os.chdir(config.PASTA)
    os.makedirs(config.caminho("modelos"), exist_ok=True)
    print("Baixando modelos:")
    try:
        for nome, (url, cab) in MODELOS.items():
            baixar(nome, url, cab)
    except Exception as e:
        print("\nERRO:", e)
        sys.exit(1)
    config.carregar()
    protecao.autostart(True)
    print("Início com o Windows: ligado.")
    if not protecao.esta_rodando("guardiao"):
        protecao.iniciar_guardiao()
    print("Bloqueador iniciado.")
