"""
Bloqueador de conteúdo sensível para Windows (estilo mosaico de TV japonesa).

Captura a tela, detecta nudez com IA local (NudeNet + classificador NSFW)
e cobre com mosaico, em qualquer navegador ou app.
Ajustes: config.json (criado na primeira execução).

Sair: Ctrl + Alt + Shift + Q
"""
import ctypes
import os
import sys
import threading
import time
import tkinter as tk

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk

from bloqueador import config, regioes
from bloqueador.detectores import criar_detectores

user32 = ctypes.windll.user32 if os.name == "nt" else None


def tornar_dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            user32.SetProcessDPIAware()
        except Exception:
            pass


class Overlay:
    """Janela transparente, sempre no topo, que deixa o mouse passar
    e é excluída da captura (assim a IA sempre enxerga a tela original)."""

    def __init__(self, esq, topo, larg, alt):
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{larg}x{alt}+{esq}+{topo}")
        self.root.config(bg="black")
        self.root.attributes("-transparentcolor", "black")
        self.canvas = tk.Canvas(self.root, width=larg, height=alt,
                                bg="black", highlightthickness=0)
        self.canvas.pack()
        self.root.update_idletasks()
        self.fotos = []

        hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        GWL_EXSTYLE = -20
        estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo | 0x80000 | 0x20 | 0x80)
        WDA_EXCLUDEFROMCAPTURE = 0x11
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            print("Aviso: seu Windows não suporta excluir a janela da captura "
                  "(precisa do Windows 10 versão 2004 ou mais novo). "
                  "O mosaico pode piscar.")

    def desenhar(self, patches):
        self.canvas.delete("all")
        self.fotos = []
        for x, y, img in patches:
            foto = ImageTk.PhotoImage(img)
            self.fotos.append(foto)
            self.canvas.create_image(x, y, image=foto, anchor="nw")


def mosaico(frame, x1, y1, x2, y2, bloco):
    recorte = frame[y1:y2, x1:x2]
    h, w = recorte.shape[:2]
    pequeno = cv2.resize(recorte, (max(1, w // bloco), max(1, h // bloco)),
                         interpolation=cv2.INTER_LINEAR)
    grande = cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)
    return Image.fromarray(cv2.cvtColor(grande, cv2.COLOR_BGR2RGB))


def titulo_janela():
    try:
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value.lower()
    except Exception:
        return ""


class Estado:
    def __init__(self):
        self.patches = []
        self.versao = 0
        self.lock = threading.Lock()
        self.rodando = True


class Medidor:
    """Média do tempo por ciclo, impressa a cada N segundos."""

    def __init__(self, a_cada=5.0):
        self.a_cada = a_cada
        self.somas = {}
        self.n = 0
        self.inicio = time.time()

    def add(self, **tempos):
        for k, v in tempos.items():
            self.somas[k] = self.somas.get(k, 0) + v
        self.n += 1
        if time.time() - self.inicio >= self.a_cada:
            partes = " | ".join(f"{k} {v / self.n * 1000:.0f}ms"
                                for k, v in self.somas.items())
            print(f"[tempo] {self.n / (time.time() - self.inicio):.1f} ciclos/s | {partes}")
            self.somas, self.n, self.inicio = {}, 0, time.time()


def trabalhador(monitor, estado, cfg):
    debug = cfg["debug"]
    detectores = criar_detectores(cfg)
    for d in detectores:
        print(f"Detector '{d.nome}' usando {getattr(d, 'dispositivo', '?')}")
    medidor = Medidor()
    palavras = [p.lower() for p in cfg["palavras_titulo"]]
    ultimo_achado = 0.0
    ultimo_log = ""
    with mss.MSS() as sct:
        while estado.rodando:
            t0 = time.perf_counter()
            frame = np.ascontiguousarray(np.array(sct.grab(monitor))[:, :, :3])
            H, W = frame.shape[:2]
            t1 = time.perf_counter()

            titulo = titulo_janela()
            titulo_ruim = any(p in titulo for p in palavras)
            achados = []
            if not titulo_ruim:
                try:
                    imagens = regioes.regioes_de_imagem(frame)
                    for d in detectores:
                        achados += d.analisar(frame, imagens)
                except Exception as e:
                    print("Erro na detecção:", e)
            t2 = time.perf_counter()

            if debug:
                linhas = [f"  {a.origem} {a.pontos:.2f} {'BLOQUEIA' if a.bloquear else 'ok'}"
                          f" {tuple(int(v) for v in a.box)} | {' | '.join(a.detalhes)}"
                          for a in sorted(achados, key=lambda a: -a.pontos)
                          if a.pontos >= 0.3 or a.bloquear]
                log = "\n".join(linhas)
                if titulo_ruim:
                    log = "  título proibido: " + titulo[:60]
                if log and log != ultimo_log:
                    print(time.strftime("%H:%M:%S"), f"[{W}x{H}] janela: {titulo[:50]!r}")
                    print(log)
                ultimo_log = log

            novos = []
            m = cfg["margem"]
            for a in achados:
                if not a.bloquear:
                    continue
                x1, y1, x2, y2 = a.box
                mx, my = (x2 - x1) * m / 2, (y2 - y1) * m / 2
                x1, y1 = int(max(0, x1 - mx)), int(max(0, y1 - my))
                x2, y2 = int(min(W, x2 + mx)), int(min(H, y2 + my))
                if x2 - x1 >= 4 and y2 - y1 >= 4:
                    novos.append((x1, y1, mosaico(frame, x1, y1, x2, y2, cfg["bloco"])))
            if titulo_ruim or (novos and cfg["modo"] == "tela"):
                novos = [(0, 0, mosaico(frame, 0, 0, W, H, cfg["bloco_tela"]))]

            agora = time.time()
            with estado.lock:
                if novos:
                    estado.patches = novos
                    estado.versao += 1
                    ultimo_achado = agora
                elif estado.patches and agora - ultimo_achado > cfg["persistencia"]:
                    estado.patches = []
                    estado.versao += 1

            t3 = time.perf_counter()
            if debug:
                medidor.add(captura=t1 - t0, ia=t2 - t1, mosaico=t3 - t2, total=t3 - t0)
            resto = cfg["intervalo"] - (t3 - t0)
            if resto > 0:
                time.sleep(resto)


def main():
    if os.name != "nt":
        print("Este app é só para Windows.")
        sys.exit(1)

    cfg = config.carregar()
    tornar_dpi_aware()
    with mss.MSS() as sct:
        monitor = dict(sct.monitors[1])  # monitor principal

    overlay = Overlay(monitor["left"], monitor["top"],
                      monitor["width"], monitor["height"])
    estado = Estado()
    threading.Thread(target=trabalhador, args=(monitor, estado, cfg),
                     daemon=True).start()

    ultima_versao = [-1]

    def atualizar():
        # Ctrl + Alt + Shift + Q para sair
        teclas = [user32.GetAsyncKeyState(k) & 0x8000
                  for k in (0x11, 0x12, 0x10, 0x51)]
        if all(teclas):
            estado.rodando = False
            overlay.root.destroy()
            return
        with estado.lock:
            patches = list(estado.patches)
            versao = estado.versao
        if versao != ultima_versao[0]:
            ultima_versao[0] = versao
            overlay.desenhar(patches)
        overlay.root.after(60, atualizar)

    print("Bloqueador ativo. Para sair: Ctrl + Alt + Shift + Q")
    overlay.root.after(60, atualizar)
    overlay.root.mainloop()


if __name__ == "__main__":
    main()
