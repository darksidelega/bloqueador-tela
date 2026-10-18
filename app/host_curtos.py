"""Host de native messaging: o Chrome executa este programa e pergunta, pela
entrada padrão, se deve esconder os vídeos curtos. Responde lendo o config
efetivo (no modo restrito, continua ligado mesmo com o config.json editado).

Protocolo do Chrome: 4 bytes (tamanho, ordem do sistema) + JSON em UTF-8.
Só usa a biblioteca padrão — roda com qualquer Python, sem o .venv."""
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def ler_mensagem(entrada):
    cabecalho = entrada.read(4)
    if len(cabecalho) < 4:
        return None
    (tamanho,) = struct.unpack("=I", cabecalho)
    corpo = entrada.read(tamanho)
    try:
        return json.loads(corpo.decode("utf-8"))
    except ValueError:
        return {}


def enviar(saida, obj):
    dados = json.dumps(obj).encode("utf-8")
    saida.write(struct.pack("=I", len(dados)))
    saida.write(dados)
    saida.flush()


def ajuste():
    try:
        from bloqueador import protecao
        cfg = protecao.config_efetivo()
        return {"bloquear_shorts": bool(cfg.get("bloquear_shorts")),
                "restrito": protecao.restrito_ativo()}
    except Exception as e:
        # na dúvida, não esconde (não "quebra" o site por um erro do app)
        return {"bloquear_shorts": False, "restrito": False, "erro": repr(e)}


def main():
    entrada = getattr(sys.stdin, "buffer", None)
    saida = getattr(sys.stdout, "buffer", None)
    if entrada is None or saida is None:
        return  # sem pipes (não foi o Chrome que abriu)
    while True:
        msg = ler_mensagem(entrada)
        if msg is None:
            break
        enviar(saida, ajuste())


if __name__ == "__main__":
    main()
