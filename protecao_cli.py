"""Ativa/desativa a autoproteção. Rode como administrador.
  python protecao_cli.py ativar      -> senha + início com Windows + sites
  python protecao_cli.py desativar   -> pede senha e remove tudo
  python protecao_cli.py senha       -> troca a senha
"""
import getpass
import os
import sys
import time

import psutil

from bloqueador import config, protecao, sites


def pedir_nova_senha():
    while True:
        s1 = getpass.getpass("Nova senha (não aparece ao digitar): ")
        if len(s1) < 4:
            print("Use pelo menos 4 caracteres.")
            continue
        if s1 == getpass.getpass("Repita a senha: "):
            return s1
        print("As senhas não batem, tente de novo.")


def conferir_senha():
    if not protecao.tem_senha():
        return True
    for _ in range(3):
        if protecao.verificar_senha(getpass.getpass("Senha atual: ")):
            return True
        print("Senha errada.")
    return False


def processos_do_app():
    meus = []
    for p in psutil.process_iter(["pid", "cmdline"]):
        cmd = " ".join(p.info["cmdline"] or []).lower()
        if p.pid != os.getpid() and ("bloqueador_tela" in cmd or "guardiao" in cmd):
            meus.append(p)
    return meus


def ativar():
    cfg = config.carregar()
    if protecao.tem_senha():
        print("Já existe senha. Para trocar: protecao_cli.py senha")
    else:
        protecao.definir_senha(pedir_nova_senha())
        print("Senha salva.")
    protecao.criar_tarefa()
    print("Tarefa agendada criada (inicia no logon e volta em até 1 min se fechada).")
    sites.aplicar(config.caminho(cfg["sites_bloqueados"]), cfg["forcar_safesearch"])
    print("Sites bloqueados no hosts.")
    protecao.cancelar_pausa()
    protecao.iniciar_guardiao()
    print("Guardião iniciado. Pronto!")


def desativar():
    if not conferir_senha():
        sys.exit(1)
    protecao.pausar(60 * 24 * 365)  # guardião para de reiniciar
    protecao.remover_tarefa()
    sites.remover()
    for p in processos_do_app():
        try:
            p.kill()
        except psutil.Error:
            pass
    time.sleep(1)
    protecao.cancelar_pausa()
    print("Proteção desativada: tarefa removida, hosts limpo, processos fechados.")


def trocar_senha():
    if not conferir_senha():
        sys.exit(1)
    protecao.definir_senha(pedir_nova_senha())
    print("Senha trocada.")


if __name__ == "__main__":
    os.chdir(config.PASTA)
    if not sites.eh_admin():
        print("Rode como administrador.")
        sys.exit(1)
    acao = sys.argv[1] if len(sys.argv) > 1 else ""
    {"ativar": ativar, "desativar": desativar, "senha": trocar_senha}.get(
        acao, lambda: print(__doc__))()
