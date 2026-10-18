"""
Bloqueador de conteúdo sensível para Windows (estilo mosaico de TV japonesa).

Captura a tela, detecta nudez com IA (NudeNet) e cobre só a área
detectada com um mosaico, em qualquer navegador ou app.

Sair: Ctrl + Alt + Shift + Q
"""
import ctypes
import os
import sys
import tempfile
import threading
import time
import tkinter as tk

import cv2
import mss
import numpy as np
from nudenet import NudeDetector
from PIL import Image, ImageTk

# ---------------- Configurações ----------------
# Classe -> pontuação mínima para bloquear (menor = bloqueia mais fácil).
# "EXPOSED" = parte à mostra; "COVERED" = coberta (mão, roupa íntima).
# Homens sem camisa (UFC) NÃO ativam: MALE_BREAST não está na lista.
CLASSES_BLOQUEAR = {
    "FEMALE_BREAST_EXPOSED": 0.45,      # alto para não pegar peito de homem (UFC)
    "FEMALE_GENITALIA_EXPOSED": 0.22,
    "MALE_GENITALIA_EXPOSED": 0.30,
    "ANUS_EXPOSED": 0.30,
    "BUTTOCKS_EXPOSED": 0.50,
    "FEMALE_GENITALIA_COVERED": 0.55,   # pega mão/roupa cobrindo
}
# Se o título da janela/aba ativa tiver alguma dessas palavras, cobre a tela.
PALAVRAS_TITULO = [
    "porn", "pornô", "xxx", "xvideos", "xnxx", "xhamster", "redtube",
    "youporn", "hentai", "nsfw", "onlyfans", "putaria", "brazzers",
    "chaturbate", "nudes", "sexo explícito",
]
USAR_FATIAS = True   # analisa a tela em pedaços também (acha imagens pequenas)
DEBUG = True         # mostra no cmd o que foi detectado e a pontuação
MODO = "tela"        # "tela" = cobre a tela inteira | "parte" = só a área detectada
BLOCO_TELA = 45      # tamanho do mosaico no modo "tela" (maior = mais borrado)
INTERVALO = 0.12     # segundos entre análises
MARGEM = 0.30        # aumenta a caixa do mosaico em 30%
BLOCO = 14           # tamanho do "pixelão" do mosaico
PERSISTENCIA = 0.7   # segundos mantendo o mosaico após sumir a detecção
# -----------------------------------------------

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


class Detector:
    def __init__(self):
        self.det = NudeDetector()
        self.usar_array = True

    def detectar(self, frame):
        if self.usar_array:
            try:
                return self.det.detect(frame)
            except Exception:
                self.usar_array = False
        caminho = os.path.join(tempfile.gettempdir(), "_bt_frame.jpg")
        cv2.imwrite(caminho, frame)
        return self.det.detect(caminho)

    def detectar_tudo(self, frame):
        """Analisa a tela inteira e, opcionalmente, 4 pedaços sobrepostos
        (o modelo enxerga em baixa resolução, então pedaços acham mais coisas)."""
        H, W = frame.shape[:2]
        regioes = [(0, 0, W, H)]
        if USAR_FATIAS:
            tw, th = int(W * 0.6), int(H * 0.6)
            for x0 in (0, W - tw):
                for y0 in (0, H - th):
                    regioes.append((x0, y0, tw, th))
        saida = []
        for x0, y0, tw, th in regioes:
            pedaco = np.ascontiguousarray(frame[y0:y0 + th, x0:x0 + tw])
            for r in self.detectar(pedaco):
                x, y, w, h = r["box"]
                saida.append({"class": r["class"], "score": r["score"],
                              "box": [x + x0, y + y0, w, h]})
        return saida


def mosaico(frame, x1, y1, x2, y2, bloco=None):
    bloco = bloco or BLOCO
    recorte = frame[y1:y2, x1:x2]
    h, w = recorte.shape[:2]
    pequeno = cv2.resize(recorte, (max(1, w // bloco), max(1, h // bloco)),
                         interpolation=cv2.INTER_LINEAR)
    grande = cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)
    return Image.fromarray(cv2.cvtColor(grande, cv2.COLOR_BGR2RGB))


def titulo_bloqueado():
    """True se o título da janela ativa (inclui a aba do navegador) tiver
    alguma palavra proibida."""
    try:
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        titulo = buf.value.lower()
    except Exception:
        return False
    return any(p in titulo for p in PALAVRAS_TITULO)


class Estado:
    def __init__(self):
        self.patches = []
        self.versao = 0
        self.lock = threading.Lock()
        self.rodando = True


def trabalhador(monitor, estado):
    detector = Detector()
    ultimo_achado = 0.0
    with mss.mss() as sct:
        while estado.rodando:
            inicio = time.time()
            shot = sct.grab(monitor)
            frame = np.ascontiguousarray(np.array(shot)[:, :, :3])
            H, W = frame.shape[:2]

            novos = []
            titulo_ruim = titulo_bloqueado()
            try:
                resultados = [] if titulo_ruim else detector.detectar_tudo(frame)
            except Exception as e:
                print("Erro na detecção:", e)
                resultados = []

            if DEBUG:
                vistos = [f'{r["class"]} {r["score"]:.2f}' for r in resultados
                          if r["score"] >= 0.15 and not r["class"].startswith(
                              ("FACE", "FEET", "ARMPITS", "BELLY"))]
                if vistos:
                    print(time.strftime("%H:%M:%S"), " | ".join(vistos))

            for r in resultados:
                limite = CLASSES_BLOQUEAR.get(r["class"])
                if limite is None or r["score"] < limite:
                    continue
                x, y, w, h = r["box"]
                mx, my = w * MARGEM, h * MARGEM
                x1 = int(max(0, x - mx)); y1 = int(max(0, y - my))
                x2 = int(min(W, x + w + mx)); y2 = int(min(H, y + h + my))
                if x2 - x1 < 4 or y2 - y1 < 4:
                    continue
                novos.append((x1, y1, mosaico(frame, x1, y1, x2, y2)))

            if titulo_ruim or (novos and MODO == "tela"):
                novos = [(0, 0, mosaico(frame, 0, 0, W, H, BLOCO_TELA))]

            agora = time.time()
            with estado.lock:
                if novos:
                    estado.patches = novos
                    estado.versao += 1
                    ultimo_achado = agora
                elif estado.patches and agora - ultimo_achado > PERSISTENCIA:
                    estado.patches = []
                    estado.versao += 1

            resto = INTERVALO - (time.time() - inicio)
            if resto > 0:
                time.sleep(resto)


def main():
    if os.name != "nt":
        print("Este app é só para Windows.")
        sys.exit(1)

    tornar_dpi_aware()
    with mss.mss() as sct:
        monitor = dict(sct.monitors[1])  # monitor principal

    overlay = Overlay(monitor["left"], monitor["top"],
                      monitor["width"], monitor["height"])
    estado = Estado()
    threading.Thread(target=trabalhador, args=(monitor, estado),
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
