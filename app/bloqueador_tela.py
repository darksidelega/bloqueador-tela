"""
Bloqueador de conteúdo sensível para Windows (estilo mosaico de TV japonesa).

Captura a tela, detecta nudez com IA local (NudeNet + classificador NSFW)
e cobre com mosaico, em qualquer navegador ou app.
Ajustes: config.json (criado na primeira execução).

Pausar: Ctrl + Alt + Shift + Q (não funciona no modo restrito)
"""
import ctypes
import ctypes.wintypes
import json
import os
import re
import sys
import threading
import time
import tkinter as tk

import cv2
import mss
import numpy as np
import psutil
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


def _pixelar(recorte, bloco):
    h, w = recorte.shape[:2]
    pequeno = cv2.resize(recorte, (max(1, w // bloco), max(1, h // bloco)),
                         interpolation=cv2.INTER_LINEAR)
    return cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)


def _para_overlay(img_bgr):
    # preto puro é a cor transparente do overlay: evita "furos" no mosaico
    img_bgr[(img_bgr == 0).all(axis=2)] = 1
    return Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))


def mosaico_tela(frame, cfg, rect_janela, monitor):
    """Mosaico na tela toda, menos as abas/botões da janela ativa (para você
    conseguir fechar) e a barra de tarefas."""
    H, W = frame.shape[:2]
    img = _pixelar(frame, cfg["bloco_tela"])
    img[(img == 0).all(axis=2)] = 1
    ox, oy = monitor["left"], monitor["top"]
    # faixa de cima da janela ativa: abas, barra de título, minimizar/fechar
    escala = 1.0
    try:
        escala = user32.GetDpiForWindow(user32.GetForegroundWindow()) / 96 or 1.0
    except Exception:
        pass
    faixa = int(cfg["faixa_livre_px"] * escala)
    l, t, r, _ = rect_janela
    x1, x2 = max(0, l - ox), min(W, r - ox)
    y1, y2 = max(0, t - oy), min(H, t - oy + faixa)
    if faixa > 0 and x2 > x1 and y2 > y1:
        img[y1:y2, x1:x2] = 0
    # barra de tarefas = tudo fora da "área de trabalho"
    area = ctypes.wintypes.RECT()
    if cfg["liberar_barra_tarefas"] and user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):
        img[:max(0, area.top - oy)] = 0
        img[max(0, area.bottom - oy):] = 0
        img[:, :max(0, area.left - ox)] = 0
        img[:, max(0, area.right - ox):] = 0
    return Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def mosaico_suave(frame, x1, y1, x2, y2, bloco, suave):
    """Mosaico na caixa + borda de `suave` px que vai sumindo (tipo feather
    do After Effects). Retorna (x, y, imagem)."""
    H, W = frame.shape[:2]
    X1, Y1 = max(0, x1 - suave), max(0, y1 - suave)
    X2, Y2 = min(W, x2 + suave), min(H, y2 + suave)
    recorte = frame[Y1:Y2, X1:X2]
    mos = _pixelar(recorte, bloco)
    if suave <= 0:
        return X1, Y1, _para_overlay(mos)
    fora = np.ones(recorte.shape[:2], np.uint8)
    fora[y1 - Y1:y2 - Y1, x1 - X1:x2 - X1] = 0
    dist = cv2.distanceTransform(fora, cv2.DIST_L2, 3)
    a = np.clip(1 - dist / suave, 0, 1)
    a = (a * a * (3 - 2 * a))[:, :, None]          # curva suave (smoothstep)
    out = (mos * a + recorte * (1 - a)).astype(np.uint8)
    out[(out == 0).all(axis=2)] = 1
    out[a[:, :, 0] < 0.03] = 0                     # bem longe: transparente
    return X1, Y1, Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


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


_processos = {}


def janela_ativa():
    """(título em minúsculas, nome do processo, retângulo) da janela ativa."""
    hwnd = user32.GetForegroundWindow()
    titulo = titulo_janela(hwnd)
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value not in _processos:
        try:
            _processos[pid.value] = psutil.Process(pid.value).name().lower()
        except Exception:
            _processos[pid.value] = ""
    r = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return titulo, _processos[pid.value], (r.left, r.top, r.right, r.bottom)


def eh_navegador(processo, cfg):
    if not cfg["so_navegador"]:
        return True
    return processo in [n.lower() for n in cfg["navegadores"]]


def titulo_janela(hwnd=None):
    try:
        hwnd = hwnd or user32.GetForegroundWindow()
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
        self.ocr_titulo = ""    # ...mas só enquanto a página for a mesma


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
        self.recarregar()
        self.ultimo_achado = 0.0
        self.ultimo_log = ""
        self.ultimo_titulo_ruim = None
        self.parados = 0
        self.suspeito_ate = 0.0
        self.ultimo_bloqueio = ""
        self.analises = 0
        self.ms_total = 0.0
        self.status_em = time.time()

    def recarregar(self):
        """Recalcula o que depende do config (chamado quando o Painel muda algo)."""
        self.palavras = [p.lower() for p in self.cfg["palavras_titulo"]]
        self.ignorar = janelas_ignoradas(self.cfg)

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

        titulo, processo, rect_janela = janela_ativa()
        vale = eh_navegador(processo, cfg) and not any(j in titulo for j in self.ignorar)
        titulo_ruim = vale and ((cfg["titulo_ativo"] and any(p in titulo for p in self.palavras))
                                or (time.time() < estado.ocr_ate
                                    and titulo == estado.ocr_titulo))
        if not mudou and titulo_ruim == self.ultimo_titulo_ruim:
            # tela parada: mantém o que está e não gasta CPU/GPU
            self.parados += 1
            if estado.patches:
                self.ultimo_achado = time.time()
            self.escrever_status(bool(estado.patches))
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
                novos.append(mosaico_suave(frame, x1, y1, x2, y2, cfg["bloco"],
                                           cfg["suavizar_px"]))
        if titulo_ruim or (novos and cfg["modo"] == "tela"):
            novos = [(0, 0, mosaico_tela(frame, cfg, rect_janela, self.monitor))]

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
        self.analises += 1
        self.ms_total += (t3 - t0) * 1000
        if novos:
            motivo = ("título/texto" if titulo_ruim else
                      " | ".join(f"{a.origem} {a.pontos:.2f}" for a in achados if a.bloquear))
            self.ultimo_bloqueio = time.strftime("%H:%M:%S ") + motivo
        self.escrever_status(bool(novos))
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

    def escrever_status(self, bloqueando):
        """dados/status.json: o Painel lê para mostrar se está ativo."""
        agora = time.time()
        if agora - self.status_em < 2:
            return
        dur = agora - self.status_em
        status = {
            "pid": os.getpid(), "atualizado": agora, "bloqueando": bloqueando,
            "dispositivo": ", ".join(getattr(d, "dispositivo", "?") for d in self.detectores)
                           or "detecção de imagens desligada",
            "analises_s": round(self.analises / dur, 1),
            "ms": round(self.ms_total / max(1, self.analises)),
            "ultimo_bloqueio": self.ultimo_bloqueio,
        }
        self.analises, self.ms_total, self.status_em = 0, 0.0, agora
        try:
            tmp = os.path.join(config.DADOS, "status.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(status, f)
            os.replace(tmp, os.path.join(config.DADOS, "status.json"))
        except OSError:
            pass

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
    try:
        leitor = ocr.LeitorTela()
    except Exception as e:
        print("OCR desligado:", e)
        return
    with mss.MSS() as sct:
        while estado.rodando:
            oc = cfg["ocr"]  # relido a cada volta (o Painel pode mudar)
            time.sleep(oc["intervalo"])
            if not oc["ativo"]:
                continue
            titulo, processo, (l, t, r, b) = janela_ativa()
            if not eh_navegador(processo, cfg) or                     any(j in titulo for j in janelas_ignoradas(cfg)):
                continue
            try:
                t0 = time.perf_counter()
                # só a janela do navegador (mensagem no WhatsApp ao lado não conta)
                area = {"left": max(l, monitor["left"]), "top": max(t, monitor["top"])}
                area["width"] = min(r, monitor["left"] + monitor["width"]) - area["left"]
                area["height"] = min(b, monitor["top"] + monitor["height"]) - area["top"]
                if area["width"] < 50 or area["height"] < 50:
                    continue
                frame = np.array(sct.grab(area))[:, :, :3]
                achadas = ocr.achar_palavras(leitor.ler(frame), oc["palavras"])
                if cfg["debug"] and achadas:
                    print(f"[ocr] {achadas} ({(time.perf_counter() - t0) * 1000:.0f}ms)")
                if achadas:
                    estado.ocr_ate = time.time() + oc["persistencia"]
                    estado.ocr_titulo = titulo
            except Exception as e:
                print("Erro no OCR:", e)


def vigiar_hosts(estado, cfg):
    """Reaplica o bloqueio de sites se alguém apagar do hosts (precisa admin)."""
    if not sites.eh_admin():
        return  # sem admin: quem aplica o hosts é o Painel
    lista = config.caminho(cfg["sites_bloqueados"])
    while estado.rodando:
        try:
            if sites.aplicar(lista, cfg["forcar_safesearch"], cfg["bloquear_sites"]):
                print("Bloqueio de sites aplicado no hosts.")
        except Exception as e:
            print("Erro ao aplicar hosts:", e)
        time.sleep(60)


def vigiar_guardiao(estado):
    """Se a proteção está instalada e alguém matar o guardião, sobe de novo."""
    if not (protecao.autostart_ativo() or protecao.tarefa_existe()):
        return
    while estado.rodando:
        time.sleep(10)
        if estado.rodando and not protecao.esta_rodando("guardiao"):
            print("Guardião não está rodando; iniciando.")
            try:
                protecao.iniciar_guardiao()
            except Exception as e:
                print("Erro ao iniciar guardião:", e)


# mudar estas chaves troca os modelos de IA: aí precisa reiniciar o app
PRECISA_REINICIAR = ("detectores", "dispositivo", "nudenet", "classificador")


def janela_pausa(root, ao_confirmar):
    """Atalho de pausa. No modo restrito só avisa até quando ele vale."""
    jan = tk.Toplevel(root)
    jan.title("Bloqueador de Tela")
    jan.attributes("-topmost", True)
    jan.resizable(False, False)
    jan.configure(bg="white", padx=18, pady=14)
    try:
        jan.iconbitmap(os.path.join(config.APP, "recursos", "icone.ico"))
    except tk.TclError:
        pass
    fonte = ("Segoe UI", 11)
    ate = protecao.restrito_ate()
    if ate:
        tk.Label(jan, text="🔒  Modo restrito ativo", font=("Segoe UI", 13, "bold"),
                 bg="white").pack(anchor="w")
        tk.Label(jan, text="Não dá para pausar até " +
                 time.strftime("%d/%m às %H:%M", time.localtime(ate)) + ".",
                 font=fonte, bg="white").pack(anchor="w", pady=(4, 10))
        tk.Button(jan, text="Ok", width=10, command=jan.destroy).pack()
    else:
        tk.Label(jan, text="Pausar o bloqueador por:", font=("Segoe UI", 13, "bold"),
                 bg="white").pack(anchor="w", pady=(0, 10))
        linha = tk.Frame(jan, bg="white")
        linha.pack()
        for txt, m in (("15 min", 15), ("30 min", 30), ("1 hora", 60), ("2 horas", 120)):
            tk.Button(linha, text=txt, width=8, font=fonte,
                      command=lambda m=m: (jan.destroy(), ao_confirmar(m))).pack(side="left", padx=3)
        tk.Button(jan, text="Cancelar", font=fonte, relief="flat", bg="white",
                  command=jan.destroy).pack(pady=(10, 0))
    jan.bind("<Escape>", lambda _: jan.destroy())
    jan.after(60_000, lambda: jan.winfo_exists() and jan.destroy())
    jan.focus_force()
    return jan


def main():
    if os.name != "nt":
        print("Este app é só para Windows.")
        sys.exit(1)

    if not protecao.instancia_unica("app"):
        return  # já tem um bloqueador rodando
    os.chdir(config.PASTA)
    configurar_log()
    protecao.cancelar_pausa()  # abriu o app = quer proteção agora
    try:  # ícone próprio na barra de tarefas (em vez do Python)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BloqueadorTela.Motor")
    except Exception:
        pass
    cfg = config.carregar()
    Saida.palavras = cfg["palavras_titulo"] + cfg["ocr"]["palavras"]
    tornar_dpi_aware()
    with mss.MSS() as sct:
        monitor = dict(sct.monitors[1])  # monitor principal

    overlay = Overlay(monitor["left"], monitor["top"],
                      monitor["width"], monitor["height"])
    estado = Estado()
    trabalhador = Trabalhador(monitor, estado, cfg)
    threading.Thread(target=trabalhador.rodar, daemon=True).start()
    threading.Thread(target=vigiar_hosts, args=(estado, cfg), daemon=True).start()
    threading.Thread(target=vigiar_guardiao, args=(estado,), daemon=True).start()
    threading.Thread(target=vigiar_ocr, args=(monitor, estado, cfg), daemon=True).start()

    ultima_versao = [-1]
    dialogo = [None]
    reiniciar = [False]
    mtime_cfg = [os.path.getmtime(config.CAMINHO)]
    tick = [0]

    def fechar(minutos):
        if not protecao.pausar(minutos):
            return  # modo restrito ligou no meio tempo
        print(f"Pausado por {minutos} min.")
        estado.rodando = False
        overlay.root.destroy()

    def atualizar():
        # Ctrl + Alt + Shift + Q: pausar (ou aviso do modo restrito)
        teclas = [user32.GetAsyncKeyState(k) & 0x8000
                  for k in (0x11, 0x12, 0x10, 0x51)]
        if all(teclas) and (dialogo[0] is None or not dialogo[0].winfo_exists()):
            dialogo[0] = janela_pausa(overlay.root, fechar)
        if dialogo[0] is not None and dialogo[0].winfo_exists():
            dialogo[0].lift()  # sempre por cima do mosaico
        tick[0] += 1
        if tick[0] % 30 == 0:  # ~2 s: o Painel mudou o config?
            try:
                m = os.path.getmtime(config.CAMINHO)
            except OSError:
                m = mtime_cfg[0]
            if m != mtime_cfg[0]:
                mtime_cfg[0] = m
                novo = config.carregar()
                if any(novo[k] != cfg[k] for k in PRECISA_REINICIAR):
                    print("Config mudou (modelos); reiniciando.")
                    reiniciar[0] = True
                    estado.rodando = False
                    overlay.root.destroy()
                    return
                cfg.clear()
                cfg.update(novo)  # as threads usam o mesmo dicionário
                trabalhador.recarregar()
                Saida.palavras = cfg["palavras_titulo"] + cfg["ocr"]["palavras"]
                print("Config atualizado.")
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
    if reiniciar[0]:
        protecao.liberar_mutexes()
        protecao.iniciar_app()


if __name__ == "__main__":
    main()
