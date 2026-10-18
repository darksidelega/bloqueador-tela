"""
Bloqueador de conteúdo sensível para Windows (estilo mosaico de TV japonesa).

Captura a tela, detecta nudez com IA local (NudeNet + classificador NSFW)
e cobre com mosaico, em qualquer navegador ou app.
Ajustes: config.json (criado na primeira execução).

Fechar/pausar: Ctrl + Alt + Shift + Q (pede a senha, se houver)
"""
import ctypes
import os
import re
import sys
import threading
import time
import tkinter as tk

import cv2
import mss
import numpy as np
from PIL import Image, ImageTk

from bloqueador import config, ocr, protecao, regioes, sites
from bloqueador.captura import Captura
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


def janelas_ignoradas(cfg):
    lista = cfg.get("ignorar_janelas", []) + cfg["ocr"].get("ignorar_janelas", [])
    return [j.lower() for j in lista]


def mascarar(texto, palavras):
    """Troca 'porn' por 'p**n' no log, para o log nunca disparar o bloqueio
    (pelo OCR ou pelo título) quando você abre ele."""
    for p in sorted(palavras, key=len, reverse=True):
        if len(p) >= 3:
            texto = re.sub(re.escape(p), lambda m: m.group()[0] + "*" * (len(m.group()) - 2)
                           + m.group()[-1], texto, flags=re.IGNORECASE)
    return texto


def titulo_janela():
    try:
        hwnd = user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value.lower()
    except Exception:
        return ""


class Saida:
    """Escreve no console (se houver) e em logs/bloqueador.log."""

    lock = threading.Lock()
    local = threading.local()
    palavras = []

    def __init__(self, console, caminho):
        self.console = console
        self.arq = open(caminho, "a", encoding="utf-8", buffering=1)

    def write(self, txt):
        # junta por linha e por thread (senão threads misturam as linhas)
        buf = getattr(self.local, "buf", "") + txt
        if "\n" not in buf:
            self.local.buf = buf
            return
        corte = buf.rindex("\n") + 1
        self.local.buf, txt = buf[corte:], buf[:corte]
        txt = mascarar(txt, Saida.palavras)
        with self.lock:
            self.arq.write(txt)
            if self.console:
                try:
                    self.console.write(txt)
                except UnicodeEncodeError:
                    self.console.write(txt.encode("ascii", "replace").decode())
                self.console.flush()

    def flush(self):
        self.arq.flush()
        if self.console:
            self.console.flush()


def configurar_log():
    pasta = config.caminho("logs")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "bloqueador.log")
    if os.path.isfile(arq) and os.path.getsize(arq) > 5_000_000:
        os.replace(arq, arq + ".old")
    sys.stdout = Saida(sys.stdout, arq)
    sys.stderr = Saida(sys.stderr, arq)


class Estado:
    def __init__(self):
        self.patches = []
        self.versao = 0
        self.lock = threading.Lock()
        self.rodando = True
        self.ocr_ate = 0.0      # cobre a tela até este horário (OCR achou palavra)


class Medidor:
    """Média do tempo por ciclo, impressa a cada N segundos."""

    def __init__(self, a_cada=5.0):
        self.a_cada = a_cada
        self.somas = {}
        self.contagens = {}
        self.n = 0
        self.inicio = time.time()

    def contar(self, **qtd):
        for k, v in qtd.items():
            self.contagens[k] = self.contagens.get(k, 0) + v

    def add(self, **tempos):
        for k, v in tempos.items():
            self.somas[k] = self.somas.get(k, 0) + v
        self.n += 1
        if time.time() - self.inicio >= self.a_cada:
            parados = self.somas.pop("parados", 0)
            partes = " | ".join(f"{k} {v / self.n * 1000:.0f}ms"
                                for k, v in self.somas.items())
            partes += f" | {parados} ciclos pulados (tela parada)"
            if self.contagens:
                partes += " | por análise: " + ", ".join(
                    f"{k} {v / self.n:.1f}x" for k, v in self.contagens.items())
            self.contagens = {}
            print(f"[tempo] {self.n / (time.time() - self.inicio):.1f} análises/s | {partes}")
            self.somas, self.n, self.inicio = {}, 0, time.time()


class Trabalhador:
    """Laço de captura + detecção. Roda numa thread separada do overlay."""

    def __init__(self, monitor, estado, cfg):
        self.monitor, self.estado, self.cfg = monitor, estado, cfg
        self.palavras = [p.lower() for p in cfg["palavras_titulo"]]
        self.ignorar = janelas_ignoradas(cfg)
        self.ultimo_achado = 0.0
        self.ultimo_log = ""
        self.ultimo_titulo_ruim = None
        self.parados = 0
        self.suspeito_ate = 0.0

    def rodar(self):
        self.detectores = criar_detectores(self.cfg)
        for d in self.detectores:
            print(f"Detector '{d.nome}' usando {getattr(d, 'dispositivo', '?')}")
        self.captura = Captura(self.monitor)
        print("Captura de tela:", self.captura.metodo)
        self.medidor = Medidor()
        while self.estado.rodando:
            try:
                self.ciclo()
            except Exception as e:
                print("Erro no ciclo:", repr(e))
                time.sleep(1)

    def ciclo(self):
        cfg, estado = self.cfg, self.estado
        t0 = time.perf_counter()
        frame, mudou = self.captura.pegar()
        H, W = frame.shape[:2]
        t1 = time.perf_counter()

        titulo = titulo_janela()
        ignorada = any(j in titulo for j in self.ignorar)
        titulo_ruim = not ignorada and (any(p in titulo for p in self.palavras)
                                        or time.time() < estado.ocr_ate)
        if not mudou and titulo_ruim == self.ultimo_titulo_ruim:
            # tela parada: mantém o que está e não gasta CPU/GPU
            self.parados += 1
            if estado.patches:
                self.ultimo_achado = time.time()
            self.dormir(t0)
            return
        self.ultimo_titulo_ruim = titulo_ruim

        achados = []
        if not titulo_ruim:
            try:
                imagens = regioes.regioes_de_imagem(frame)
                for d in self.detectores:
                    achados += d.analisar(frame, imagens)
            except Exception as e:
                print("Erro na detecção:", repr(e))
        t2 = time.perf_counter()

        if cfg["debug"]:
            self.logar(achados, titulo, titulo_ruim, W, H)
        if titulo_ruim or any(a.pontos >= 0.4 for a in achados):
            self.suspeito_ate = time.time() + 3  # analisa mais rápido por 3 s

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
                self.ultimo_achado = agora
            elif estado.patches and agora - self.ultimo_achado > cfg["persistencia"]:
                estado.patches = []
                estado.versao += 1

        t3 = time.perf_counter()
        if cfg["debug"]:
            self.medidor.add(captura=t1 - t0, ia=t2 - t1, mosaico=t3 - t2,
                             total=t3 - t0, parados=self.parados)
            self.parados = 0
            for d in self.detectores:
                if hasattr(d, "cache_det"):
                    self.medidor.contar(nudenet=d.cache_det.execucoes,
                                        classificador=d.cache_clf.execucoes)
                    d.cache_det.execucoes = d.cache_clf.execucoes = 0
        self.dormir(t0)

    def dormir(self, t0):
        intervalo = self.cfg["intervalo_rapido" if time.time() < self.suspeito_ate
                             else "intervalo"]
        resto = intervalo - (time.perf_counter() - t0)
        if resto > 0:
            time.sleep(resto)

    def logar(self, achados, titulo, titulo_ruim, W, H):
        linhas = [f"  {a.origem} {a.pontos:.2f} {'BLOQUEIA' if a.bloquear else 'ok'}"
                  f" {tuple(int(v) for v in a.box)} | {' | '.join(a.detalhes)}"
                  for a in sorted(achados, key=lambda a: -a.pontos)
                  if a.pontos >= 0.3 or a.bloquear]
        log = "\n".join(linhas)
        if titulo_ruim:
            log = "  título/texto proibido: " + titulo[:60]
        if log and log != self.ultimo_log:
            print(time.strftime("%H:%M:%S"), f"[{W}x{H}] janela: {titulo[:50]!r}")
            print(log)
        self.ultimo_log = log


def vigiar_ocr(monitor, estado, cfg):
    """Lê o texto da tela a cada poucos segundos e cobre tudo se achar
    palavra proibida."""
    oc = cfg["ocr"]
    try:
        leitor = ocr.LeitorTela()
    except Exception as e:
        print("OCR desligado:", e)
        return
    ignorar = janelas_ignoradas(cfg)
    with mss.MSS() as sct:
        while estado.rodando:
            time.sleep(oc["intervalo"])
            titulo = titulo_janela()
            if any(j in titulo for j in ignorar):
                continue
            try:
                t0 = time.perf_counter()
                frame = np.array(sct.grab(monitor))[:, :, :3]
                achadas = ocr.achar_palavras(leitor.ler(frame), oc["palavras"])
                if cfg["debug"] and achadas:
                    print(f"[ocr] {achadas} ({(time.perf_counter() - t0) * 1000:.0f}ms)")
                if achadas:
                    estado.ocr_ate = time.time() + oc["persistencia"]
            except Exception as e:
                print("Erro no OCR:", e)


def vigiar_hosts(estado, cfg):
    """Reaplica o bloqueio de sites se alguém apagar do hosts (precisa admin)."""
    if not sites.eh_admin():
        print("Aviso: sem admin, o bloqueio de sites (hosts) não é verificado.")
        return
    lista = config.caminho(cfg["sites_bloqueados"])
    while estado.rodando:
        try:
            if sites.aplicar(lista, cfg["forcar_safesearch"]):
                print("Bloqueio de sites aplicado no hosts.")
        except Exception as e:
            print("Erro ao aplicar hosts:", e)
        time.sleep(60)


def vigiar_guardiao(estado):
    """Se a proteção está instalada e alguém matar o guardião, sobe de novo."""
    if not protecao.tarefa_existe():
        return
    while estado.rodando:
        time.sleep(10)
        if estado.rodando and not protecao.esta_rodando("guardiao"):
            print("Guardião não está rodando; iniciando.")
            try:
                protecao.iniciar_guardiao()
            except Exception as e:
                print("Erro ao iniciar guardião:", e)


def janela_senha(root, ao_confirmar):
    """Pede a senha e por quantos minutos pausar."""
    jan = tk.Toplevel(root)
    jan.title("Bloqueador - pausar")
    jan.attributes("-topmost", True)
    jan.resizable(False, False)
    tk.Label(jan, text="Senha:").grid(row=0, column=0, padx=8, pady=6, sticky="e")
    senha = tk.Entry(jan, show="*", width=24)
    senha.grid(row=0, column=1, padx=8, pady=6)
    tk.Label(jan, text="Pausar por (min):").grid(row=1, column=0, padx=8, sticky="e")
    minutos = tk.Spinbox(jan, from_=5, to=1440, increment=5, width=6)
    minutos.delete(0, "end")
    minutos.insert(0, "60")
    minutos.grid(row=1, column=1, padx=8, sticky="w")
    aviso = tk.Label(jan, text="", fg="red")
    aviso.grid(row=2, column=0, columnspan=2)

    def ok(_=None):
        if protecao.verificar_senha(senha.get()):
            try:
                m = max(1, int(minutos.get()))
            except ValueError:
                m = 60
            jan.destroy()
            ao_confirmar(m)
        else:
            senha.delete(0, "end")
            aviso.config(text="Senha errada")

    tk.Button(jan, text="Pausar", command=ok).grid(row=3, column=0, columnspan=2, pady=8)
    jan.bind("<Return>", ok)
    jan.bind("<Escape>", lambda _: jan.destroy())
    jan.after(60_000, lambda: jan.winfo_exists() and jan.destroy())
    jan.focus_force()
    senha.focus_set()
    return jan


def main():
    if os.name != "nt":
        print("Este app é só para Windows.")
        sys.exit(1)

    if not protecao.instancia_unica("app"):
        return  # já tem um bloqueador rodando
    configurar_log()
    protecao.cancelar_pausa()  # abriu o app = quer proteção agora
    cfg = config.carregar()
    Saida.palavras = cfg["palavras_titulo"] + cfg["ocr"]["palavras"]
    tornar_dpi_aware()
    with mss.MSS() as sct:
        monitor = dict(sct.monitors[1])  # monitor principal

    overlay = Overlay(monitor["left"], monitor["top"],
                      monitor["width"], monitor["height"])
    estado = Estado()
    threading.Thread(target=Trabalhador(monitor, estado, cfg).rodar,
                     daemon=True).start()
    threading.Thread(target=vigiar_hosts, args=(estado, cfg), daemon=True).start()
    threading.Thread(target=vigiar_guardiao, args=(estado,), daemon=True).start()
    if cfg["ocr"]["ativo"]:
        threading.Thread(target=vigiar_ocr, args=(monitor, estado, cfg),
                         daemon=True).start()

    ultima_versao = [-1]
    dialogo = [None]

    def fechar(minutos):
        protecao.pausar(minutos)
        print(f"Pausado por {minutos} min.")
        estado.rodando = False
        overlay.root.destroy()

    def atualizar():
        # Ctrl + Alt + Shift + Q: pede senha para pausar/fechar
        teclas = [user32.GetAsyncKeyState(k) & 0x8000
                  for k in (0x11, 0x12, 0x10, 0x51)]
        if all(teclas):
            if not protecao.tem_senha():
                fechar(60)
                return
            if dialogo[0] is None or not dialogo[0].winfo_exists():
                dialogo[0] = janela_senha(overlay.root, fechar)
        if dialogo[0] is not None and dialogo[0].winfo_exists():
            dialogo[0].lift()  # senha sempre por cima do mosaico
        with estado.lock:
            patches = list(estado.patches)
            versao = estado.versao
        if versao != ultima_versao[0]:
            ultima_versao[0] = versao
            overlay.desenhar(patches)
        overlay.root.after(60, atualizar)

    print("Bloqueador ativo. Para pausar/fechar: Ctrl + Alt + Shift + Q")
    overlay.root.after(60, atualizar)
    overlay.root.mainloop()


if __name__ == "__main__":
    main()
