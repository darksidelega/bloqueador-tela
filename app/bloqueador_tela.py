"""
Bloqueador de conteúdo sensível para Windows (estilo mosaico de TV japonesa).

Captura a tela, detecta nudez com IA local (NudeNet + classificador NSFW)
e cobre com mosaico, em qualquer navegador ou app.
Ajustes: config.json (criado na primeira execução).

Pausar: Ctrl + Alt + Shift + Q (não funciona no modo restrito)
Bloqueio rápido: Ctrl + Alt + Shift + B (liga o modo restrito na hora)
"""
import ctypes
import ctypes.wintypes
import json
import os
import re
import struct
import sys
import threading
import time
import tkinter as tk
from collections import namedtuple

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

        hwnd = self.hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        GWL_EXSTYLE = -20
        estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # LAYERED | TRANSPARENT (click-through) | TOOLWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo | 0x80000 | 0x20 | 0x80)
        WDA_EXCLUDEFROMCAPTURE = 0x11
        if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
            print("Aviso: seu Windows não suporta excluir a janela da captura "
                  "(precisa do Windows 10 versão 2004 ou mais novo). "
                  "O mosaico pode piscar.")

    _u32 = None

    def para_o_topo(self):
        """O Windows rebaixa o mosaico para trás de janelas normais (Fotos,
        Explorador) e de outras "sempre no topo"; isto o traz de volta.
        Os tipos precisam ser de 64 bits: com int o Windows recebia um handle
        inválido (erro 1400) e nada acontecia."""
        if Overlay._u32 is None:
            u = Overlay._u32 = ctypes.WinDLL("user32")
            u.SetWindowPos.argtypes = (ctypes.wintypes.HWND, ctypes.wintypes.HWND, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint)
        HWND_TOPMOST, SWP_NOSIZE_NOMOVE_NOACTIVATE = -1, 0x0013
        Overlay._u32.SetWindowPos(self.hwnd, ctypes.wintypes.HWND(HWND_TOPMOST),
                                  0, 0, 0, 0, SWP_NOSIZE_NOMOVE_NOACTIVATE)

    def desenhar(self, patches, capas=()):
        """patches: (x, y, imagem) de mosaico. capas: retângulos cobertos
        com cor sólida na hora (scroll, Alt+Tab, miniatura da barra)."""
        self.canvas.delete("all")
        self.fotos = []
        for x, y, img in patches:
            foto = ImageTk.PhotoImage(img)
            self.fotos.append(foto)
            self.canvas.create_image(x, y, image=foto, anchor="nw")
        for x1, y1, x2, y2 in capas:
            self.canvas.create_rectangle(x1, y1, x2, y2, fill="#3b3b40", width=0)
            if x2 - x1 > 220 and y2 - y1 > 60:
                self.canvas.create_text((x1 + x2) / 2, (y1 + y2) / 2, fill="#d0d0d8",
                                        text="🔒 conteúdo sensível", font=("Segoe UI", 14))


def _pixelar(recorte, bloco):
    h, w = recorte.shape[:2]
    pequeno = cv2.resize(recorte, (max(1, w // bloco), max(1, h // bloco)),
                         interpolation=cv2.INTER_LINEAR)
    return cv2.resize(pequeno, (w, h), interpolation=cv2.INTER_NEAREST)


def _no_frame(rect, monitor):
    l, t, r, b = rect
    ox, oy = monitor["left"], monitor["top"]
    return l - ox, t - oy, r - ox, b - oy


def _apagar(img, rects, ox=0, oy=0):
    """Deixa transparentes (preto puro) os `rects` dentro de `img`, que começa
    em (ox, oy) do frame."""
    for x1, y1, x2, y2 in rects:
        img[max(0, y1 - oy):max(0, y2 - oy), max(0, x1 - ox):max(0, x2 - ox)] = 0


def faixa_abas(cfg, janela, monitor):
    """Faixa de cima da janela (abas, barra de título, minimizar/fechar), em
    coordenadas do frame, ou None se a janela está em tela cheia (F11/vídeo)."""
    x1, y1, x2, y2 = _no_frame(janela.rect, monitor)
    if (x1, y1, x2, y2) == (0, 0, monitor["width"], monitor["height"]) or cfg["faixa_livre_px"] <= 0:
        return None
    try:
        escala = user32.GetDpiForWindow(janela.hwnd) / 96 or 1.0
    except Exception:
        escala = 1.0
    return x1, y1, x2, y1 + int(cfg["faixa_livre_px"] * escala)


def dentro(box, areas):
    """O centro da caixa cai em alguma das áreas?"""
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return any(x1 <= cx < x2 and y1 <= cy < y2 for x1, y1, x2, y2 in areas)


def areas_livres(cfg, janelas, monitor):
    """O que nunca é coberto: as abas das `janelas` (para você conseguir
    fechar) e a barra de tarefas."""
    livres = [f for f in (faixa_abas(cfg, j, monitor) for j in janelas) if f]
    # barra de tarefas = tudo fora da "área de trabalho"
    area = ctypes.wintypes.RECT()
    if cfg["liberar_barra_tarefas"] and user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):
        W, H = monitor["width"], monitor["height"]
        l, t, r, b = _no_frame((area.left, area.top, area.right, area.bottom), monitor)
        livres += [(0, 0, W, t), (0, b, W, H), (0, 0, l, H), (r, 0, W, H)]
    return livres


def mosaico_areas(frame, cfg, areas, livres):
    """Mosaico grosso nas `areas` (janelas ou a tela toda), menos as `livres`.
    Retorna (0, 0, imagem do tamanho da tela)."""
    H, W = frame.shape[:2]
    img = _pixelar(frame, cfg["bloco_tela"])
    img[(img == 0).all(axis=2)] = 1
    cobrir = np.zeros((H, W), bool)
    for x1, y1, x2, y2 in areas:
        cobrir[max(0, y1):max(0, y2), max(0, x1):max(0, x2)] = True
    img[~cobrir] = 0
    _apagar(img, livres)
    return 0, 0, Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))


def mosaico_caixas(frame, caixas, bloco, suave, livres=()):
    """Mosaico em todas as caixas + borda de `suave` px que vai sumindo (tipo
    feather do After Effects), menos as `livres`. Uma imagem só para todas
    (uma por caixa levava ~10 ms cada: com 20 fotos na tela o scroll travava).
    Retorna (x, y, imagem)."""
    H, W = frame.shape[:2]
    X1 = max(0, min(c[0] for c in caixas) - suave)
    Y1 = max(0, min(c[1] for c in caixas) - suave)
    X2 = min(W, max(c[2] for c in caixas) + suave)
    Y2 = min(H, max(c[3] for c in caixas) + suave)
    recorte = frame[Y1:Y2, X1:X2]
    mos = _pixelar(recorte, bloco)
    fora = np.ones(recorte.shape[:2], np.uint8)
    for x1, y1, x2, y2 in caixas:
        fora[max(0, y1 - Y1):max(0, y2 - Y1), max(0, x1 - X1):max(0, x2 - X1)] = 0
    if suave > 0:
        dist = cv2.distanceTransform(fora, cv2.DIST_L2, 3)
        a = np.clip(1 - dist / suave, 0, 1)
        a = a * a * (3 - 2 * a)                    # curva suave (smoothstep)
        out = cv2.blendLinear(mos, recorte, a, 1 - a)
    else:
        out, a = mos, 1 - fora
    out[(out == 0).all(axis=2)] = 1                # preto puro é a cor transparente
    out[a < 0.03] = 0                              # bem longe: transparente
    _apagar(out, livres, X1, Y1)
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
Janela = namedtuple("Janela", "hwnd titulo processo rect")


def _janela(hwnd):
    """Janela com título em minúsculas, nome do processo e retângulo."""
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value not in _processos:
        try:
            _processos[pid.value] = psutil.Process(pid.value).name().lower()
        except Exception:
            _processos[pid.value] = ""
    r = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return Janela(hwnd, titulo_janela(hwnd), _processos[pid.value],
                  (r.left, r.top, r.right, r.bottom))


def janela_ativa():
    return _janela(user32.GetForegroundWindow())


_ENUM = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def janelas_visiveis():
    """Janelas visíveis na tela, da que está na frente para a de trás
    (minimizadas e escondidas em outra área de trabalho ficam de fora)."""
    hwnds = []

    def juntar(hwnd, _):
        if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd) \
                and user32.GetWindowTextLengthW(hwnd):
            oculta = ctypes.c_int(0)
            DWMWA_CLOAKED = 14
            ctypes.windll.dwmapi.DwmGetWindowAttribute(
                hwnd, DWMWA_CLOAKED, ctypes.byref(oculta), ctypes.sizeof(oculta))
            if not oculta.value:
                hwnds.append(hwnd)
        return True
    user32.EnumWindows(_ENUM(juntar), 0)
    return [_janela(h) for h in hwnds]


# Alt+Tab e Visão de Tarefas (Win+Tab): mostram miniaturas das janelas
CLASSES_ALTERNANCIA = ("XamlExplorerHostIslandWindow", "MultitaskingViewFrame",
                       "TaskSwitcherWnd", "ForegroundStaging")


def classe_janela(hwnd):
    buf = ctypes.create_unicode_buffer(128)
    user32.GetClassNameW(hwnd, buf, 128)
    return buf.value


def janela_raiz_em(x, y):
    """Janela principal que está no ponto (o mosaico deixa o mouse passar,
    então não conta)."""
    h = user32.WindowFromPoint(ctypes.wintypes.POINT(int(x), int(y)))
    return user32.GetAncestor(h, 2) if h else 0  # GA_ROOT


def _subtrair(rects, b):
    """Tira o retângulo b de cada retângulo da lista (sobram até 4 pedaços)."""
    bx1, by1, bx2, by2 = b
    sobra = []
    for x1, y1, x2, y2 in rects:
        if bx1 >= x2 or bx2 <= x1 or by1 >= y2 or by2 <= y1:
            sobra.append((x1, y1, x2, y2))
            continue
        if by1 > y1:
            sobra.append((x1, y1, x2, by1))
        if by2 < y2:
            sobra.append((x1, by2, x2, y2))
        meio_y1, meio_y2 = max(y1, by1), min(y2, by2)
        if bx1 > x1:
            sobra.append((x1, meio_y1, bx1, meio_y2))
        if bx2 < x2:
            sobra.append((bx2, meio_y1, x2, meio_y2))
    return sobra


def partes_visiveis(hwnd, rect):
    """Pedaços de `rect` que não estão escondidos por janelas na frente de
    hwnd (cobrir a janela inteira cobriria o terminal aberto por cima dela)."""
    partes = [rect]
    for j in janelas_visiveis():
        if j.hwnd == hwnd:
            break
        pid = ctypes.c_ulong()
        user32.GetWindowThreadProcessId(j.hwnd, ctypes.byref(pid))
        if pid.value != os.getpid():
            partes = _subtrair(partes, j.rect)
    return partes


# nome do produto gravado dentro do .exe (renomear o arquivo não muda isso)
PRODUTOS_NAVEGADOR = ("chrome", "edge", "firefox", "brave", "opera", "vivaldi",
                      "chromium", "thorium", "librewolf", "waterfox")
_produtos = {}


def _nome_do_produto(caminho):
    v = ctypes.windll.version
    n = v.GetFileVersionInfoSizeW(caminho, None)
    if not n:
        return ""
    buf = ctypes.create_string_buffer(n)
    p, tam = ctypes.c_void_p(), ctypes.c_uint()
    if not v.GetFileVersionInfoW(caminho, 0, n, buf) or not v.VerQueryValueW(
            buf, "\\VarFileInfo\\Translation", ctypes.byref(p), ctypes.byref(tam)) \
            or tam.value < 4:
        return ""
    lingua, pagina = struct.unpack("<HH", ctypes.string_at(p.value, 4))
    if v.VerQueryValueW(buf, f"\\StringFileInfo\\{lingua:04x}{pagina:04x}\\ProductName",
                        ctypes.byref(p), ctypes.byref(tam)) and tam.value:
        return ctypes.wstring_at(p.value, tam.value).rstrip("\0").lower()
    return ""


def navegador_de_verdade(janela):
    """O processo é um navegador, pelo nome ou pelo produto dentro do .exe?
    (WebView2, usado dentro de outros apps, não conta)."""
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(janela.hwnd, ctypes.byref(pid))
    if pid.value not in _produtos:
        try:
            _produtos[pid.value] = _nome_do_produto(psutil.Process(pid.value).exe())
        except Exception:
            _produtos[pid.value] = ""
    produto = _produtos[pid.value]
    # palavra inteira: "Microsoft Windows Operating System" (Explorador) não é "opera"
    return "webview" not in produto and any(
        re.search(rf"\b{n}\b", produto) for n in PRODUTOS_NAVEGADOR)


def eh_navegador(janela, cfg):
    if not cfg["so_navegador"]:
        return True
    return janela.processo in [n.lower() for n in cfg["navegadores"]] \
        or navegador_de_verdade(janela)


def navegadores_visiveis(cfg, monitor):
    """Janelas de navegador visíveis neste monitor onde título/OCR valem.
    A lista de "ignorar" (terminal, editor...) não vale para navegador: senão
    pesquisar "porn python" fazia a página ser ignorada."""
    ignorar = janelas_ignoradas(cfg)
    ml, mt = monitor["left"], monitor["top"]
    mr, mb = ml + monitor["width"], mt + monitor["height"]
    return [j for j in janelas_visiveis()
            if eh_navegador(j, cfg) and j.processo != "pythonw.exe"
            and (navegador_de_verdade(j) or not any(i in j.titulo for i in ignorar))
            and j.rect[0] < mr and j.rect[2] > ml and j.rect[1] < mb and j.rect[3] > mt]


def titulo_janela(hwnd=None):
    try:
        hwnd = hwnd or user32.GetForegroundWindow()
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value.lower()
    except Exception:
        return ""


MAX_LOG = 3_000_000  # tamanho do log ativo antes de arquivar


def limpar_logs(pasta, dias):
    """Apaga os logs arquivados com mais de `dias` dias (0 = nunca), para a
    pasta não crescer sem parar. Não mexe no log ativo (bloqueador.log)."""
    if dias <= 0:
        return
    corte = time.time() - dias * 86400
    try:
        for nome in os.listdir(pasta):
            caminho = os.path.join(pasta, nome)
            if nome == "bloqueador.log" or not nome.startswith("bloqueador.log"):
                continue
            try:
                if os.path.getmtime(caminho) < corte:
                    os.remove(caminho)
            except OSError:
                pass
    except OSError:
        pass


class Saida:
    """Escreve no console (se houver) e em logs/bloqueador.log, arquivando o
    log quando passa de MAX_LOG e apagando arquivos antigos (não fica pesado)."""

    lock = threading.Lock()
    local = threading.local()
    palavras = []

    def __init__(self, console, caminho, dias):
        self.console = console
        self.caminho = caminho
        self.dias = dias
        self.desde_conferiu = 0
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
            self.desde_conferiu += len(txt)
            if self.desde_conferiu > 200_000:  # confere o tamanho de vez em quando
                self.desde_conferiu = 0
                self._talvez_arquivar()
            if self.console:
                try:
                    self.console.write(txt)
                except UnicodeEncodeError:
                    self.console.write(txt.encode("ascii", "replace").decode())
                self.console.flush()

    def _talvez_arquivar(self):
        try:
            if self.arq.tell() < MAX_LOG:
                return
        except (OSError, ValueError):
            return
        self.arq.close()
        try:  # bloqueador.log -> bloqueador.log.AAAAMMDD-HHMMSS
            os.replace(self.caminho, self.caminho + time.strftime(".%Y%m%d-%H%M%S"))
        except OSError:
            pass
        self.arq = open(self.caminho, "a", encoding="utf-8", buffering=1)
        limpar_logs(os.path.dirname(self.caminho), self.dias)

    def flush(self):
        self.arq.flush()
        if self.console:
            self.console.flush()


def configurar_log(dias=7):
    pasta = config.caminho("logs")
    os.makedirs(pasta, exist_ok=True)
    arq = os.path.join(pasta, "bloqueador.log")
    if os.path.isfile(arq) and os.path.getsize(arq) > MAX_LOG:
        try:
            os.replace(arq, arq + time.strftime(".%Y%m%d-%H%M%S"))
        except OSError:
            pass
    limpar_logs(pasta, dias)
    # um só objeto para stdout e stderr: um dono do arquivo, um lock, um arquivamento
    saida = Saida(sys.stdout, arq, dias)
    sys.stdout = sys.stderr = saida


class Estado:
    def __init__(self):
        self.patches = []
        self.versao = 0
        self.lock = threading.Lock()
        self.rodando = True
        self.ocr_ate = 0.0      # cobre a janela até este horário (OCR achou palavra)
        self.ocr_titulo = ""    # ...mas só enquanto a página for a mesma
        self.sensivel_ate = 0.0  # print bloqueado até este horário
        self.print_barrado = False
        self.rolando_ate = 0.0   # rolando a página: cobre a janela inteira
        self.ciclo_pronto = 0.0  # início da última análise já desenhada
        # janelas que mostraram conteúdo sensível: {hwnd: (título, quando)}
        # (Alt+Tab e a miniatura da barra mostram elas sem mosaico)
        self.janelas_sensiveis = {}
        # páginas com muitas fotos sensíveis + palavra: {hwnd: título}
        # ficam cobertas inteiras até mudar de página
        self.paginas_travadas = {}
        self.sensivel_qtd = 0    # quantas fotos sensíveis na última análise

    # cobrir a janela/tela inteira (ao rolar, Alt+Tab) só com várias fotos
    # sensíveis: uma só não escurece a página toda (segurança p/ falso positivo)
    MIN_COBRIR_TUDO = 2

    def com_imagens(self, hwnd, titulo=None):
        """Esta página (mesma janela e mesmo título) está mostrando VÁRIAS
        fotos sensíveis agora? Palavra sozinha não conta, nem a página anterior
        da mesma janela do Chrome, nem uma única foto."""
        if titulo is None:
            titulo = titulo_janela(hwnd)
        return (time.time() < self.sensivel_ate and self.sensivel_qtd >= self.MIN_COBRIR_TUDO
                and self.janelas_sensiveis.get(hwnd, (None,))[0] == titulo)

    def rolando_sensivel(self):
        """Mexeu na roda/teclas numa página que está mostrando fotos sensíveis?"""
        return self.com_imagens(user32.GetForegroundWindow())

    def tem_janela_sensivel(self):
        agora = time.time()
        for hwnd, (titulo, quando) in list(self.janelas_sensiveis.items()):
            if agora - quando < 600 and user32.IsWindow(hwnd) and titulo_janela(hwnd) == titulo:
                return True
            self.janelas_sensiveis.pop(hwnd, None)
        return False


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
        self.achou = False       # a última análise cobriu algo?
        self.anterior = None     # frame reduzido anterior (detecta scroll)
        self.analises = 0
        self.ms_total = 0.0
        self.status_em = time.time()

    def recarregar(self):
        """Recalcula o que depende do config (chamado quando o Painel muda algo)."""
        self.palavras = [p.lower() for p in self.cfg["palavras_titulo"]]

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

        ativa = janela_ativa()
        titulo = ativa.titulo
        if not eh_navegador(ativa, cfg):
            # o OCR só lê o navegador ativo: com outra janela na frente ele
            # não confere de novo, então a marcação da página continua valendo
            estado.ocr_ate = max(estado.ocr_ate, time.time() + 1)
        # navegadores com palavra proibida (título ou texto): a palavra sozinha
        # não cobre nada, só deixa a IA mais exigente com as imagens deles.
        # Vale para todo navegador visível, não só o ativo: senão abrir o
        # Explorador ou a Captura por cima do navegador libera as imagens.
        ruins = [j for j in navegadores_visiveis(cfg, self.monitor) if self.proibido(j.titulo)]
        areas_ruins = [_no_frame(j.rect, self.monitor) for j in ruins]
        titulo_ruim = tuple((j.hwnd, j.rect) for j in ruins)
        if not mudou and titulo_ruim == self.ultimo_titulo_ruim:
            # tela parada: mantém o que está e não gasta CPU/GPU
            self.parados += 1
            with estado.lock:
                if estado.patches and self.achou:
                    self.ultimo_achado = time.time()
                elif estado.patches and time.time() - self.ultimo_achado > cfg["persistencia"]:
                    # a última análise não achou nada: tira o mosaico velho
                    # (antes ele ficava até a tela mudar de novo, ex.: um clique)
                    estado.patches = []
                    estado.versao += 1
            estado.ciclo_pronto = time.time()  # tela igual à última analisada
            self.escrever_status(bool(estado.patches))
            self.dormir(t0)
            return
        self.ultimo_titulo_ruim = titulo_ruim
        inicio = time.time()
        self.detectar_scroll(frame, ativa)

        achados = []
        try:
            imagens = regioes.regioes_de_imagem(frame)
            for d in self.detectores:
                achados += d.analisar(frame, imagens)
        except Exception as e:
            print("Erro na detecção:", repr(e))
        for a in achados:
            if not a.bloquear and a.pontos >= cfg["limiar_com_palavra"] \
                    and dentro(a.box, areas_ruins):
                a.bloquear = True
                a.detalhes.append("(página com palavra proibida)")
        t2 = time.perf_counter()

        if cfg["debug"]:
            self.logar(achados, titulo, ruins, W, H)
        if titulo_ruim or any(a.pontos >= 0.4 for a in achados):
            self.suspeito_ate = time.time() + 3  # analisa mais rápido por 3 s

        caixas = []
        livres = areas_livres(cfg, [ativa] + ruins, self.monitor)
        m = cfg["margem"]
        agora = time.time()
        for a in achados:
            if not a.bloquear:
                continue
            x1, y1, x2, y2 = a.box
            hwnd = janela_raiz_em(self.monitor["left"] + (x1 + x2) / 2,
                                  self.monitor["top"] + (y1 + y2) / 2)
            if hwnd:
                estado.janelas_sensiveis[hwnd] = (titulo_janela(hwnd), agora)
            mx, my = (x2 - x1) * m / 2, (y2 - y1) * m / 2
            x1, y1 = int(max(0, x1 - mx)), int(max(0, y1 - my))
            x2, y2 = int(min(W, x2 + mx)), int(min(H, y2 + my))
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                caixas.append((x1, y1, x2, y2))
        for j, area in zip(ruins, areas_ruins):
            fotos = sum(1 for a in achados if a.bloquear and dentro(a.box, [area]))
            if fotos >= cfg["travar_pagina_fotos"] and j.hwnd not in estado.paginas_travadas:
                estado.paginas_travadas[j.hwnd] = j.titulo
                print(f"Página travada ({fotos} fotos sensíveis + palavra): {j.titulo[:60]}")
        novos = [mosaico_caixas(frame, caixas, cfg["bloco"], cfg["suavizar_px"],
                                livres)] if caixas else []
        self.achou = bool(novos)
        if novos and cfg["modo"] == "tela":
            novos = [mosaico_areas(frame, cfg, [(0, 0, W, H)], livres)]

        agora = time.time()
        with estado.lock:
            if novos:
                estado.patches = novos
                estado.versao += 1
                self.ultimo_achado = agora
                estado.sensivel_ate = agora + 3
                estado.sensivel_qtd = len(caixas)
            elif estado.patches and agora - self.ultimo_achado > cfg["persistencia"]:
                estado.patches = []
                estado.versao += 1
            estado.ciclo_pronto = inicio

        t3 = time.perf_counter()
        self.analises += 1
        self.ms_total += (t3 - t0) * 1000
        if novos:
            motivo = " | ".join(f"{a.origem} {a.pontos:.2f}" for a in achados if a.bloquear)
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

    def detectar_scroll(self, frame, ativa):
        """Plano B do scroll (touchpad às vezes não manda a roda do mouse):
        se a tela mudou muito numa janela que tinha conteúdo sensível, cobre
        ela inteira até parar."""
        peq = frame[::16, ::16].astype(np.int16)
        anterior, self.anterior = self.anterior, peq
        mesma, self.ultima_ativa = getattr(self, "ultima_ativa", None) == ativa.hwnd, ativa.hwnd
        if anterior is None or anterior.shape != peq.shape or not mesma:
            return  # trocar de janela (Alt+Tab) também muda tudo: não é scroll
        if self.estado.com_imagens(ativa.hwnd, ativa.titulo):
            mudou = (np.abs(peq - anterior).sum(axis=2) > 60).mean()
            if mudou > 0.12:
                self.estado.rolando_ate = time.time() + 0.5

    def proibido(self, titulo):
        """Título com palavra proibida, ou página onde o OCR achou uma."""
        return bool((self.cfg["titulo_ativo"] and ocr.achar_palavras(titulo, self.palavras))
                    or (time.time() < self.estado.ocr_ate and titulo == self.estado.ocr_titulo))

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

    def logar(self, achados, titulo, ruins, W, H):
        linhas = [f"  palavra proibida (imagens mais exigentes): {j.titulo[:60]}"
                  for j in ruins] + [
                  f"  {a.origem} {a.pontos:.2f} {'BLOQUEIA' if a.bloquear else 'ok'}"
                  f" {tuple(int(v) for v in a.box)} | {' | '.join(a.detalhes)}"
                  for a in sorted(achados, key=lambda a: -a.pontos)
                  if a.pontos >= 0.3 or a.bloquear]
        log = "\n".join(linhas)
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
            # só o navegador ativo: lendo um que está atrás, o OCR lia o texto
            # da janela que estava por cima dele
            ativa = janela_ativa()
            if not eh_navegador(ativa, cfg) or (not navegador_de_verdade(ativa) and any(
                    j in ativa.titulo for j in janelas_ignoradas(cfg))):
                continue
            titulo, (l, t, r, b) = ativa.titulo, ativa.rect
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
        if protecao.restrito_indefinido():
            d = protecao.desbloqueio_em()
            quando = ("Desbloqueia às " + time.strftime("%H:%M", time.localtime(d)) + "."
                      if d else "Sem prazo: peça o desbloqueio no Painel e espere.")
        else:
            quando = "Não dá para pausar até " + time.strftime("%d/%m às %H:%M",
                                                               time.localtime(ate)) + "."
        tk.Label(jan, text="🔒  Modo restrito ativo", font=("Segoe UI", 13, "bold"),
                 bg="white").pack(anchor="w")
        tk.Label(jan, text=quando, font=fonte, bg="white").pack(anchor="w", pady=(4, 10))
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


class _Tecla(ctypes.Structure):
    _fields_ = [("vkCode", ctypes.wintypes.DWORD), ("scanCode", ctypes.wintypes.DWORD),
                ("flags", ctypes.wintypes.DWORD), ("time", ctypes.wintypes.DWORD),
                ("dwExtraInfo", ctypes.c_size_t)]


_HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                               ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)


def barrar_print(estado):
    """Com conteúdo sensível na tela, descarta PrtSc e Win + Shift + S.
    A tela congelada da Captura fica numa camada acima de qualquer programa
    (o mosaico não consegue cobrir) e o print sairia sem o mosaico.
    Precisa rodar na thread do Tk (que processa as mensagens do Windows)."""
    u32 = ctypes.WinDLL("user32")  # instância própria: argtypes não vazam
    u32.SetWindowsHookExW.argtypes = (ctypes.c_int, _HOOKPROC, ctypes.c_void_p,
                                      ctypes.wintypes.DWORD)
    u32.SetWindowsHookExW.restype = ctypes.c_void_p
    u32.CallNextHookEx.argtypes = (ctypes.c_void_p, ctypes.c_int,
                                   ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM)
    u32.CallNextHookEx.restype = ctypes.c_ssize_t
    apertada = lambda vk: u32.GetAsyncKeyState(vk) & 0x8000

    TECLAS_SCROLL = (0x20, 0x21, 0x22, 0x23, 0x24, 0x26, 0x28)  # espaço, PgUp/Dn, End, Home, setas

    def ao_teclar(n, wparam, lparam):
        if n == 0 and time.time() < estado.sensivel_ate:
            vk = ctypes.cast(lparam, ctypes.POINTER(_Tecla)).contents.vkCode
            win = apertada(0x5B) or apertada(0x5C)
            if vk == 0x2C or (vk == 0x53 and win and apertada(0x10)):  # PrtSc | Win+Shift+S
                estado.print_barrado = True
                return 1
            if vk in TECLAS_SCROLL and wparam in (0x100, 0x104) and estado.rolando_sensivel():
                estado.rolando_ate = time.time() + 0.5
        return u32.CallNextHookEx(None, n, wparam, lparam)

    def ao_mover(n, wparam, lparam):
        # roda do mouse numa página com conteúdo sensível: cobre na hora,
        # antes das fotos novas aparecerem (a IA leva ~0,1 s para ver)
        if n == 0 and wparam in (0x20A, 0x20E) and estado.rolando_sensivel():
            estado.rolando_ate = time.time() + 0.5
        return u32.CallNextHookEx(None, n, wparam, lparam)

    # guardar, senão o Python libera
    barrar_print.callbacks = (_HOOKPROC(ao_teclar), _HOOKPROC(ao_mover))
    k32 = ctypes.WinDLL("kernel32")
    k32.GetModuleHandleW.restype = ctypes.c_void_p  # handle de 64 bits
    WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
    for tipo, cb in zip((WH_KEYBOARD_LL, WH_MOUSE_LL), barrar_print.callbacks):
        if not u32.SetWindowsHookExW(tipo, cb, k32.GetModuleHandleW(None), 0):
            print("Aviso: não consegui ligar o gancho de teclado/mouse", tipo)


def fechar_print(cfg, estado):
    """Se um app de print abriu mesmo assim (botão "Novo" da Captura, por
    exemplo) com conteúdo sensível na tela, fecha ele."""
    if time.time() >= estado.sensivel_ate:
        return
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), ctypes.byref(pid))
    try:
        p = psutil.Process(pid.value)
        if p.name().lower() in cfg["apps_de_print"]:
            p.kill()
            estado.print_barrado = True
            print("App de print fechado:", p.name())
    except Exception:
        pass


def janela_aviso(root, titulo, texto, segundos=30):
    """Aviso no canto de baixo da tela, por cima de tudo (some sozinho)."""
    jan = tk.Toplevel(root)
    jan.title("Bloqueador de Tela")
    jan.attributes("-topmost", True)
    jan.resizable(False, False)
    jan.configure(bg="white", padx=18, pady=14)
    try:
        jan.iconbitmap(os.path.join(config.APP, "recursos", "icone.ico"))
    except tk.TclError:
        pass
    tk.Label(jan, text=titulo, font=("Segoe UI", 13, "bold"), bg="white").pack(anchor="w")
    tk.Label(jan, text=texto, font=("Segoe UI", 11), bg="white", justify="left",
             wraplength=340).pack(anchor="w", pady=(4, 10))
    tk.Button(jan, text="Ok", width=10, command=jan.destroy).pack(anchor="e")
    jan.update_idletasks()
    area = ctypes.wintypes.RECT()
    if user32.SystemParametersInfoW(0x30, 0, ctypes.byref(area), 0):
        x = area.right - jan.winfo_reqwidth() - 40
        y = area.bottom - jan.winfo_reqheight() - 70
        jan.geometry(f"+{x}+{y}")
    jan.bind("<Escape>", lambda _: jan.destroy())
    jan.after(segundos * 1000, lambda: jan.winfo_exists() and jan.destroy())
    return jan


class _UltimaEntrada(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def parado_ha():
    """Segundos desde a última vez que mexeram no mouse ou teclado."""
    info = _UltimaEntrada(ctypes.sizeof(_UltimaEntrada), 0)
    user32.GetLastInputInfo(ctypes.byref(info))
    return ((ctypes.windll.kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000


class Lembrete:
    """Conta o tempo seguido usando o PC e avisa para dar uma pausa."""

    def __init__(self):
        self.desde = time.time()

    def hora_da_pausa(self, cfg):
        lp = cfg["lembrete_pausa"]
        agora = time.time()
        if not lp["ativo"] or parado_ha() >= lp["pausa_conta_min"] * 60:
            self.desde = agora  # desligado ou ficou longe do PC (já é uma pausa)
            return False
        if agora - self.desde >= lp["minutos"] * 60:
            self.desde = agora
            return True
        return False


def main():
    if os.name != "nt":
        print("Este app é só para Windows.")
        sys.exit(1)

    if protecao.aberto_pelo_lancador():
        protecao.iniciar_app()  # reabre direto, fora do lançador (que é desprotegido)
        return
    if not protecao.instancia_unica("app"):
        return  # já tem um bloqueador rodando
    os.chdir(config.PASTA)
    configurar_log(config.carregar().get("dias_log", 7))
    protecao.cancelar_pausa()  # abriu o app = quer proteção agora
    try:  # ícone próprio na barra de tarefas (em vez do Python)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BloqueadorTela.Motor")
    except Exception:
        pass
    restrito = protecao.vigiar_restrito()
    protecao.travar_arquivos(restrito)
    protecao.proteger_processo(restrito)
    cfg = protecao.config_efetivo()
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
    avisos = []
    lembrete = Lembrete()
    tecla_b = [False]
    reiniciar = [False]
    restrito_antes = [restrito]
    tick = [0]

    def fechar(minutos):
        if not protecao.pausar(minutos):
            return  # modo restrito ligou no meio tempo
        print(f"Pausado por {minutos} min.")
        estado.rodando = False
        overlay.root.destroy()

    capas_antes = [[]]

    def calcular_capas():
        """Coberturas sólidas desenhadas na hora pela thread do Tk (sem
        esperar a IA): scroll, Alt+Tab/Win+Tab e miniatura da barra."""
        capas, agora = [], time.time()
        ox, oy = monitor["left"], monitor["top"]
        ativa = user32.GetForegroundWindow()
        alternando = classe_janela(ativa) in CLASSES_ALTERNANCIA
        # rolando: a janela ativa inteira (menos as abas) até a IA olhar a
        # tela parada de novo
        if (agora < estado.rolando_ate or estado.ciclo_pronto < estado.rolando_ate) and not alternando:
            j = _janela(ativa)
            x1, y1, x2, y2 = _no_frame(j.rect, monitor)
            faixa = faixa_abas(cfg, j, monitor)
            capas.append((max(0, x1), max(0, faixa[3] if faixa else y1),
                          min(monitor["width"], x2), min(monitor["height"], y2)))
        if alternando and estado.janelas_sensiveis and estado.tem_janela_sensivel():
            capas.append((0, 0, monitor["width"], monitor["height"]))
        # páginas travadas: a janela inteira menos as abas, só a parte visível
        for hwnd, titulo in list(estado.paginas_travadas.items()):
            if not user32.IsWindow(hwnd) or titulo_janela(hwnd) != titulo:
                estado.paginas_travadas.pop(hwnd, None)  # mudou de página
                continue
            if alternando or not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                continue
            j = _janela(hwnd)
            faixa = faixa_abas(cfg, j, monitor)
            x1, y1, x2, y2 = j.rect
            y1 = faixa[3] + oy if faixa else y1
            for px1, py1, px2, py2 in partes_visiveis(hwnd, (x1, y1, x2, y2)):
                capas.append((max(0, px1 - ox), max(0, py1 - oy),
                              min(monitor["width"], px2 - ox), min(monitor["height"], py2 - oy)))
        return capas

    def atualizar():
        # Ctrl + Alt + Shift + Q: pausar (ou aviso do modo restrito)
        teclas = [user32.GetAsyncKeyState(k) & 0x8000
                  for k in (0x11, 0x12, 0x10, 0x51)]
        if all(teclas) and (dialogo[0] is None or not dialogo[0].winfo_exists()):
            dialogo[0] = janela_pausa(overlay.root, fechar)
        # Ctrl + Alt + Shift + B: bloqueio rápido (só na hora que aperta o B)
        b = all(teclas[:3]) and bool(user32.GetAsyncKeyState(0x42) & 0x8000)
        if b and not tecla_b[0]:
            ate = protecao.bloqueio_rapido()
            protecao.travar_arquivos(True)
            protecao.proteger_processo(True)
            restrito_antes[0] = True
            print("Bloqueio rápido pelo atalho.")
            avisos.append(janela_aviso(
                overlay.root, "🔒  Bloqueio rápido ativo",
                "Até " + time.strftime("%H:%M", time.localtime(ate)) + " não dá para pausar, "
                "desligar nem apagar o app. Respira: isso passa.", 15))
        tecla_b[0] = b
        if tick[0] % 4 == 0:
            fechar_print(cfg, estado)
        if estado.print_barrado:
            estado.print_barrado = False
            if not any(j.winfo_exists() and j.title() == "Print bloqueado" for j in avisos):
                aviso = janela_aviso(overlay.root, "📵  Print bloqueado",
                                     "Tem conteúdo sensível na tela agora.", 5)
                aviso.title("Print bloqueado")
                avisos.append(aviso)
        tick[0] += 1
        capas = calcular_capas()
        if capas or tick[0] % 6 == 0:
            overlay.para_o_topo()  # o Windows rebaixa o mosaico (Fotos, Alt+Tab...)
        if tick[0] % 16 == 0 and lembrete.hora_da_pausa(cfg):
            minutos = cfg["lembrete_pausa"]["minutos"]
            avisos.append(janela_aviso(
                overlay.root, "⏰  Hora de uma pausa",
                f"Você está há {minutos} minutos seguidos no PC. Levanta, bebe uma água, "
                "olha pela janela por uns minutos."))
        for j in [dialogo[0]] + avisos:
            if j is not None and j.winfo_exists():
                j.lift()  # sempre por cima do mosaico
        avisos[:] = [j for j in avisos if j.winfo_exists()]
        if tick[0] % 50 == 0:  # ~2 s: modo restrito e config
            restrito = protecao.vigiar_restrito()
            protecao.travar_arquivos(restrito)
            if restrito != restrito_antes[0]:
                restrito_antes[0] = restrito
                protecao.proteger_processo(restrito)
                print("Modo restrito", "ativo." if restrito else "acabou.")
            # no restrito, editar o config.json à mão só vale para deixar mais rígido
            novo = protecao.config_efetivo()
            if novo != cfg:
                if any(novo[k] != cfg[k] for k in PRECISA_REINICIAR):
                    print("Config mudou (modelos); reiniciando.")
                    reiniciar[0] = True
                    estado.rodando = False
                    overlay.root.destroy()
                    return
                else:
                    cfg.clear()
                    cfg.update(novo)  # as threads usam o mesmo dicionário
                    trabalhador.recarregar()
                    Saida.palavras = cfg["palavras_titulo"] + cfg["ocr"]["palavras"]
                    print("Config atualizado.")
        with estado.lock:
            patches = list(estado.patches)
            versao = estado.versao
        if versao != ultima_versao[0] or capas != capas_antes[0]:
            ultima_versao[0], capas_antes[0] = versao, capas
            overlay.desenhar(patches, capas)
        overlay.root.after(40, atualizar)

    print("Bloqueador ativo. Pausar: Ctrl + Alt + Shift + Q | bloqueio rápido: Ctrl + Alt + Shift + B")
    barrar_print(estado)
    overlay.root.after(60, atualizar)
    overlay.root.mainloop()
    if reiniciar[0]:
        protecao.liberar_mutexes()
        protecao.iniciar_app()


if __name__ == "__main__":
    main()
