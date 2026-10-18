"""Guardião: mantém o bloqueador rodando e o reinicia se for fechado
(a não ser que tenha sido pausado com a senha). Iniciado com o Windows."""
import os
import time

from bloqueador import config, protecao


def main():
    if not protecao.instancia_unica("guardiao"):
        return
    while True:
        if not protecao.pausa_ativa() and not protecao.esta_rodando("app"):
            protecao.iniciar_app()
            time.sleep(10)  # tempo para o app subir e criar o mutex
        time.sleep(3)


if __name__ == "__main__":
    os.chdir(config.PASTA)
    main()
