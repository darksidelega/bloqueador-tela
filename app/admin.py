"""Ações que precisam de administrador. O Painel chama este script elevado
(aparece o aviso do Windows).
  admin.py hosts_aplicar | hosts_remover | tarefa_criar | tarefa_remover
"""
import os
import sys

from bloqueador import config, protecao, sites


def hosts_aplicar():
    cfg = protecao.config_efetivo()
    sites.aplicar(config.caminho(cfg["sites_bloqueados"]), cfg["forcar_safesearch"],
                  cfg["bloquear_sites"])


ACOES = {
    "hosts_aplicar": hosts_aplicar,
    "hosts_remover": sites.remover,
    "tarefa_criar": protecao.criar_tarefa,
    "tarefa_remover": protecao.remover_tarefa,
}

if __name__ == "__main__":
    os.chdir(config.PASTA)
    if not sites.eh_admin():
        sys.exit(2)
    if protecao.restrito_ativo() and any(a in ("hosts_remover", "tarefa_remover")
                                         for a in sys.argv[1:]):
        sys.exit(3)  # modo restrito: não tira bloqueio nem rodando direto
    try:
        for acao in sys.argv[1:]:
            ACOES[acao]()
    except Exception as e:
        with open(os.path.join(config.PASTA, "logs", "admin_erro.log"), "a",
                  encoding="utf-8") as f:
            f.write(f"{sys.argv[1:]}: {e!r}\n")
        sys.exit(1)
