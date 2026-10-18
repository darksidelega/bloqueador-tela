"""Guardião: mantém o bloqueador rodando e o reinicia se for fechado
(a não ser que tenha sido pausado com a senha). Iniciado pela tarefa agendada."""
import os
import subprocess
import sys
import time

from bloqueador import config, protecao


def comando_app():
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [protecao.pythonw(), config.caminho("bloqueador_tela.py")]


def main():
    if not protecao.instancia_unica("guardiao"):
        return
    while True:
        if not protecao.pausa_ativa() and not protecao.esta_rodando("app"):
            subprocess.Popen(comando_app(), cwd=config.PASTA,
                             creationflags=0x08000000)
            time.sleep(10)  # tempo para o app subir e criar o mutex
        time.sleep(3)


if __name__ == "__main__":
    os.chdir(config.PASTA)
    main()
