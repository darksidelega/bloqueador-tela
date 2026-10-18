"""Bloqueio de sites pelo arquivo hosts do Windows (vale p/ todo navegador).

Escreve uma seção marcada no hosts apontando os domínios para 0.0.0.0 e,
opcionalmente, força o SafeSearch do Google/Bing/DuckDuckGo.
Precisa de privilégio de administrador.
"""
import ctypes
import os
import socket
import subprocess

HOSTS = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                     r"System32\drivers\etc\hosts")
INICIO = "# >>> bloqueador-tela (nao edite esta secao) >>>"
FIM = "# <<< bloqueador-tela <<<"

# domínio de busca -> host "seguro" cujo IP força o SafeSearch
SAFESEARCH = {
    "forcesafesearch.google.com": [
        "www.google.com", "google.com", "www.google.com.br", "google.com.br",
        "images.google.com", "images.google.com.br",
    ],
    "strict.bing.com": ["www.bing.com", "bing.com"],
    "safe.duckduckgo.com": ["duckduckgo.com", "www.duckduckgo.com"],
}


def eh_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def ler_lista(caminho):
    dominios = []
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            d = linha.split("#")[0].strip().lower()
            if d:
                d = d.removeprefix("http://").removeprefix("https://").strip("/")
                dominios.append(d.removeprefix("www."))
    return sorted(set(dominios))


def montar_secao(dominios, safesearch=True):
    linhas = [INICIO]
    for d in dominios:
        linhas += [f"0.0.0.0 {d}", f"0.0.0.0 www.{d}"]
    if safesearch:
        for seguro, alvos in SAFESEARCH.items():
            try:
                ip = socket.gethostbyname(seguro)
            except OSError:
                continue
            linhas += [f"{ip} {a}" for a in alvos]
    linhas.append(FIM)
    return "\n".join(linhas) + "\n"


def _ler_hosts():
    with open(HOSTS, encoding="utf-8", errors="ignore") as f:
        return f.read()


def _remover_secao(texto):
    if INICIO in texto and FIM in texto:
        a = texto.index(INICIO)
        b = texto.index(FIM) + len(FIM)
        texto = texto[:a].rstrip("\n") + "\n" + texto[b:].lstrip("\n")
    return texto


def secao_atual():
    texto = _ler_hosts()
    if INICIO in texto and FIM in texto:
        return texto[texto.index(INICIO):texto.index(FIM) + len(FIM)] + "\n"
    return ""


def secao_desejada(lista, bloquear_sites=True, safesearch=True):
    """Texto que a seção do hosts deve ter ("" = nada)."""
    if not bloquear_sites and not safesearch:
        return ""
    return montar_secao(ler_lista(lista) if bloquear_sites else [], safesearch)


def aplicar(lista, safesearch=True, bloquear_sites=True):
    """Grava a seção no hosts se mudou. Retorna True se gravou."""
    nova = secao_desejada(lista, bloquear_sites, safesearch)
    if not nova:
        mudou = bool(secao_atual())
        remover()
        return mudou
    if secao_atual() == nova:
        return False
    texto = _remover_secao(_ler_hosts()).rstrip("\n") + "\n\n" + nova
    with open(HOSTS, "w", encoding="utf-8") as f:
        f.write(texto)
    subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                   creationflags=0x08000000)  # sem janela
    return True


def remover():
    texto = _ler_hosts()
    if INICIO in texto:
        with open(HOSTS, "w", encoding="utf-8") as f:
            f.write(_remover_secao(texto))
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True,
                       creationflags=0x08000000)
