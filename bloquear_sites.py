"""Aplica a lista sites_bloqueados.txt no arquivo hosts (precisa de admin).
Uso: python bloquear_sites.py"""
import sys

from bloqueador import config, sites

if __name__ == "__main__":
    if not sites.eh_admin():
        print("Rode como administrador (use o 3_bloquear_sites.bat).")
        sys.exit(1)
    cfg = config.carregar()
    mudou = sites.aplicar(config.caminho(cfg["sites_bloqueados"]),
                          cfg["forcar_safesearch"])
    n = len(sites.ler_lista(config.caminho(cfg["sites_bloqueados"])))
    print(f"{n} sites bloqueados no hosts." + ("" if mudou else " (já estava atualizado)"))
