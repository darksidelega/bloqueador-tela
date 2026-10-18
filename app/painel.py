"""Painel do Bloqueador de Tela.

Tudo se aplica na hora (sem botão salvar). Modo restrito: até o horário
escolhido não dá para pausar nem desligar nada, só deixar mais rígido.
"""
import ctypes
import json
import os
import threading
import time

import customtkinter as ctk
import psutil
from PIL import Image

from bloqueador import atalhos, config, protecao, sites

# cores (modo claro, modo escuro)
FUNDO = ("#F3F4F6", "#111215")
CARTAO = ("#FFFFFF", "#1C1D22")
BORDA = ("#E5E7EB", "#2A2B31")
TEXTO2 = ("#6B7280", "#9CA3AF")
ACENTO = ("#4F46E5", "#6366F1")
ACENTO_HOVER = ("#4338CA", "#4F46E5")
VERDE = ("#16A34A", "#22C55E")
LARANJA = ("#D97706", "#F59E0B")
VERMELHO = ("#DC2626", "#EF4444")
ICONE = os.path.join(config.APP, "recursos", "icone.ico")
ARQ_BOAS_VINDAS = os.path.join(config.DADOS, "boas_vindas.json")


def fonte(tam=13, peso="normal"):
    return ctk.CTkFont(family="Segoe UI", size=tam, weight=peso)


def centralizar(j, pai):
    """Põe a janelinha no meio do painel."""
    j.update_idletasks()
    # reqwidth: tamanho pedido (vale mesmo antes da janela aparecer)
    w, h = j.winfo_reqwidth(), j.winfo_reqheight()
    x = pai.winfo_rootx() + (pai.winfo_width() - w) // 2
    y = pai.winfo_rooty() + max(0, (pai.winfo_height() - h) // 3)
    esc = j._get_window_scaling()  # o customtkinter multiplica a posição pela escala
    j.geometry(f"+{max(0, int(x / esc))}+{max(0, int(y / esc))}")


def por_icone(janela):
    # o customtkinter troca o ícone ~200 ms depois de criar a janela
    janela.after(300, lambda: janela.iconbitmap(ICONE))


def emoji(pai, texto, tam=20, lado=40):
    """Emoji numa caixa de largura fixa (alguns emojis são mais largos e
    desalinhavam o texto ao lado)."""
    caixa = ctk.CTkFrame(pai, fg_color="transparent", width=lado, height=lado)
    caixa.pack_propagate(False)
    texto = texto.replace("️", "")  # o Tk desenha esse seletor como espaço
    ctk.CTkLabel(caixa, text=texto, font=fonte(tam)).place(relx=0.5, rely=0.5, anchor="center")
    return caixa


def falta(ate):
    s = int(ate - time.time())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m:02d}min" if h else f"{m} min"


class Painel(ctk.CTk):
    def __init__(self):
        super().__init__(fg_color=FUNDO)
        self.title("Bloqueador de Tela")
        self.geometry("520x820")
        self.minsize(480, 560)
        por_icone(self)

        self.cfg = config.carregar()
        self.vars = {}
        self.switches = {}
        self.popup = None
        self._timer_salvar = None

        self.corpo = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.corpo.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.aviso = ctk.CTkLabel(self, text="", font=fonte(12), text_color=TEXTO2, height=26)
        self.aviso.pack(fill="x", padx=16, pady=(0, 6))

        self._cabecalho()
        self._cartao_status()
        self._cartao_restrito()
        self._cartao_bloquear()
        self._cartao_cobrir()
        self._cartao_sistema()
        ctk.CTkLabel(self.corpo, text="Atalho para pausar: Ctrl + Alt + Shift + Q",
                     font=fonte(11), text_color=TEXTO2).pack(pady=(4, 12))

        self._status()
        if not os.path.isfile(ARQ_BOAS_VINDAS):
            self.after(500, self.boas_vindas)

    # ================= montagem =================
    def _cartao(self, titulo=None, sub=None):
        c = ctk.CTkFrame(self.corpo, fg_color=CARTAO, corner_radius=14,
                         border_width=1, border_color=BORDA)
        c.pack(fill="x", padx=8, pady=6)
        if titulo:
            ctk.CTkLabel(c, text=titulo, font=fonte(15, "bold")).pack(anchor="w", padx=16, pady=(12, 0))
        if sub:
            ctk.CTkLabel(c, text=sub, font=fonte(12), text_color=TEXTO2, justify="left",
                         wraplength=430).pack(anchor="w", padx=16)
        return c

    def _linha(self, pai, icone, titulo, sub, chave, valor, comando):
        f = ctk.CTkFrame(pai, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=5)
        emoji(f, icone).pack(side="left")
        txt = ctk.CTkFrame(f, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ctk.CTkLabel(txt, text=titulo, font=fonte(13, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(txt, text=sub, font=fonte(11), text_color=TEXTO2, anchor="w",
                     justify="left", wraplength=320).pack(fill="x")
        var = ctk.BooleanVar(value=valor)
        sw = ctk.CTkSwitch(f, text="", variable=var, width=46, progress_color=ACENTO,
                           command=lambda: comando(chave))
        sw.pack(side="right")
        self.vars[chave], self.switches[chave] = var, sw
        return f

    def _cabecalho(self):
        f = ctk.CTkFrame(self.corpo, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=(6, 2))
        img = ctk.CTkImage(Image.open(os.path.join(config.APP, "recursos", "icone.png")), size=(46, 46))
        ctk.CTkLabel(f, image=img, text="").pack(side="left")
        t = ctk.CTkFrame(f, fg_color="transparent")
        t.pack(side="left", padx=10)
        ctk.CTkLabel(t, text="Bloqueador de Tela", font=fonte(20, "bold")).pack(anchor="w")
        ctk.CTkLabel(t, text="Cobre conteúdo sensível com mosaico · 100% no seu PC",
                     font=fonte(12), text_color=TEXTO2).pack(anchor="w")

    def _cartao_status(self):
        c = self._cartao()
        topo = ctk.CTkFrame(c, fg_color="transparent")
        topo.pack(fill="x", padx=16, pady=(14, 4))
        self.lb_estado = ctk.CTkLabel(topo, text="…", font=fonte(22, "bold"))
        self.lb_estado.pack(side="left")
        self.vars["ligado"] = ctk.BooleanVar(value=True)
        self.sw_ligado = ctk.CTkSwitch(topo, text="", variable=self.vars["ligado"],
                                       switch_width=56, switch_height=28, progress_color=VERDE,
                                       command=self._alternar_ligado)
        self.sw_ligado.pack(side="right")
        self.lb_info = ctk.CTkLabel(c, text="", font=fonte(12), text_color=TEXTO2)
        self.lb_info.pack(anchor="w", padx=16)
        self.lb_ultimo = ctk.CTkLabel(c, text="", font=fonte(12), text_color=TEXTO2)
        self.lb_ultimo.pack(anchor="w", padx=16, pady=(0, 14))

    def _cartao_restrito(self):
        c = self._cartao()
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=12)
        emoji(f, "🔒", 24, 44).pack(side="left")
        t = ctk.CTkFrame(f, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ctk.CTkLabel(t, text="Modo restrito", font=fonte(15, "bold"), anchor="w").pack(fill="x")
        self.lb_restrito = ctk.CTkLabel(t, text="", font=fonte(12), text_color=TEXTO2,
                                        anchor="w", justify="left", wraplength=300)
        self.lb_restrito.pack(fill="x")
        self.bt_restrito = ctk.CTkButton(f, text="Ativar", width=96, height=34, corner_radius=10,
                                         fg_color=ACENTO, hover_color=ACENTO_HOVER,
                                         font=fonte(13, "bold"), command=self.restrito)
        self.bt_restrito.pack(side="right")

    def _cartao_bloquear(self):
        c = self._cartao("O que bloquear")
        cfg = self.cfg
        self._linha(c, "🖼️", "Imagens e vídeos", "IA analisa a tela e cobre nudez",
                    "imagens", "nudez" in cfg["detectores"], self._alternar)
        linha = self._linha(c, "🌐", "Sites adultos", "Bloqueia a lista de sites em todo navegador",
                            "sites", cfg["bloquear_sites"], self._alternar)
        self.bt_lista = ctk.CTkButton(linha, text="Editar lista", width=86, height=26,
                                      fg_color="transparent", border_width=1, border_color=BORDA,
                                      text_color=ACENTO, hover_color=BORDA, font=fonte(11),
                                      command=self.editar_sites)
        self.bt_lista.pack(side="right", padx=8)
        self._linha(c, "🔎", "Busca segura", "SafeSearch sempre ligado no Google, Bing e DuckDuckGo",
                    "safesearch", cfg["forcar_safesearch"], self._alternar)
        self._linha(c, "🏷️", "Palavras no título da aba", "Ex.: abrir uma aba com nome proibido",
                    "titulo", cfg["titulo_ativo"], self._alternar)
        self._linha(c, "📝", "Texto na página", "Lê o texto do navegador (mensagens em apps não contam)",
                    "ocr", cfg["ocr"]["ativo"], self._alternar)
        ctk.CTkFrame(c, fg_color="transparent", height=6).pack()

    def _cartao_cobrir(self):
        c = self._cartao("Como cobrir")
        self.seg_modo = ctk.CTkSegmentedButton(
            c, values=["Só a área", "Tela inteira"], font=fonte(13), height=34,
            selected_color=ACENTO, selected_hover_color=ACENTO_HOVER, command=self._mudar_modo)
        self.seg_modo.set("Tela inteira" if self.cfg["modo"] == "tela" else "Só a área")
        self.seg_modo.pack(fill="x", padx=16, pady=(10, 8))

        self.sliders = {}
        itens = [
            ("sens", "Sensibilidade", 0, 100, (1.6 - self.cfg["limiar_bloqueio"]) * 100),
            ("margem", "Área extra em volta", 0, 100, self.cfg["margem"] * 100),
            ("suave", "Borda suave", 0, 120, self.cfg["suavizar_px"]),
        ]
        for chave, titulo, a, b, valor in itens:
            f = ctk.CTkFrame(c, fg_color="transparent")
            f.pack(fill="x", padx=16, pady=(4, 0))
            ctk.CTkLabel(f, text=titulo, font=fonte(13)).pack(side="left")
            lb = ctk.CTkLabel(f, text="", font=fonte(12, "bold"), text_color=ACENTO)
            lb.pack(side="right")
            s = ctk.CTkSlider(c, from_=a, to=b, progress_color=ACENTO, button_color=ACENTO,
                              button_hover_color=ACENTO_HOVER,
                              command=lambda v, k=chave: self._mover(k, v))
            s.set(valor)
            s.pack(fill="x", padx=16, pady=(2, 6))
            self.sliders[chave] = (s, lb)
            self._rotulo(chave, valor)
        ctk.CTkFrame(c, fg_color="transparent", height=6).pack()

    def _cartao_sistema(self):
        c = self._cartao("Sistema")
        self._linha(c, "🚀", "Iniciar com o Windows", "Liga sozinho quando você entra no PC",
                    "autostart", protecao.autostart_ativo(), self._alternar)
        self._linha(c, "🛡️", "Proteção forte", "Se alguém fechar, o Windows reabre em até 1 min (pede admin)",
                    "forte", protecao.tarefa_existe(), self._alternar)
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=14, pady=(8, 14))
        estilo = dict(height=32, corner_radius=10, fg_color="transparent", border_width=1,
                      border_color=BORDA, text_color=("#111827", "#E5E7EB"), hover_color=BORDA,
                      font=fonte(12))
        ctk.CTkButton(f, text="Ver log", width=90, command=lambda: self._abrir(
            os.path.join(config.PASTA, "logs", "bloqueador.log")), **estilo).pack(side="left", padx=2)
        ctk.CTkButton(f, text="Atalhos…", width=90, command=self.boas_vindas,
                      **estilo).pack(side="left", padx=2)
        estilo.update(text_color=VERMELHO, border_color=VERMELHO)
        self.bt_desligar = ctk.CTkButton(f, text="Desligar tudo", width=110,
                                         command=self.desligar_tudo, **estilo)
        self.bt_desligar.pack(side="right", padx=2)

    # ================= helpers =================
    def avisar(self, txt, cor=TEXTO2, segundos=5):
        self.aviso.configure(text=txt, text_color=cor)
        if segundos:
            self.after(segundos * 1000, lambda: self.aviso.cget("text") == txt and
                       self.aviso.configure(text=""))

    @staticmethod
    def _abrir(caminho):
        if os.path.exists(caminho):
            os.startfile(caminho)

    def _salvar_cfg(self, **mudar):
        cfg = config.carregar()
        for k, v in mudar.items():
            if k == "ocr_ativo":
                cfg["ocr"]["ativo"] = v
            else:
                cfg[k] = v
        config.salvar(cfg)   # o bloqueador percebe sozinho em ~2 s
        self.cfg = cfg

    def _admin(self, acoes, ao_falhar):
        """Roda ações de admin numa thread (o aviso do Windows não trava o painel)."""
        self.avisar("Aguardando a permissão do Windows…", ACENTO, 0)

        def rodar():
            ok = protecao.rodar_admin(*acoes)
            self.after(0, lambda: self.avisar("Aplicado ✓", VERDE) if ok else (
                ao_falhar(), self.avisar("Permissão recusada: nada foi alterado.", VERMELHO)))
        threading.Thread(target=rodar, daemon=True).start()

    # ================= ações =================
    def _alternar(self, chave):
        var = self.vars[chave]
        novo = var.get()
        if protecao.restrito_ativo() and not novo:
            var.set(True)
            self.avisar("🔒 Modo restrito: só dá para ligar proteções.", LARANJA)
            return
        if chave == "imagens":
            self._salvar_cfg(detectores=["nudez"] if novo else [])
        elif chave == "titulo":
            self._salvar_cfg(titulo_ativo=novo)
        elif chave == "ocr":
            self._salvar_cfg(ocr_ativo=novo)
        elif chave in ("sites", "safesearch"):
            nome = "bloquear_sites" if chave == "sites" else "forcar_safesearch"
            antigo = not novo
            self._salvar_cfg(**{nome: novo})
            cfg = self.cfg
            desejada = sites.secao_desejada(config.caminho(cfg["sites_bloqueados"]),
                                            cfg["bloquear_sites"], cfg["forcar_safesearch"])
            if desejada != sites.secao_atual():
                def desfazer():
                    var.set(antigo)
                    self._salvar_cfg(**{nome: antigo})
                self._admin(["hosts_aplicar"], desfazer)
                return
        elif chave == "autostart":
            protecao.autostart(novo)
            if novo and not protecao.esta_rodando("guardiao"):
                protecao.iniciar_guardiao()
        elif chave == "forte":
            self._admin(["tarefa_criar" if novo else "tarefa_remover"],
                        lambda: var.set(not novo))
            return
        self.avisar("Aplicado ✓", VERDE)

    def _mudar_modo(self, valor):
        modo = "tela" if valor == "Tela inteira" else "parte"
        if protecao.restrito_ativo() and modo == "parte" and self.cfg["modo"] == "tela":
            self.seg_modo.set("Tela inteira")
            self.avisar("🔒 Modo restrito: só dá para deixar mais rígido.", LARANJA)
            return
        self._salvar_cfg(modo=modo)
        self.avisar("Aplicado ✓", VERDE)

    def _rotulo(self, chave, v):
        _, lb = self.sliders[chave]
        if chave == "sens":
            nivel = "Baixa" if v < 35 else "Média" if v < 70 else "Alta"
            lb.configure(text=f"{nivel} · {v:.0f}%")
        elif chave == "margem":
            lb.configure(text=f"+{v:.0f}%")
        else:
            lb.configure(text=f"{v:.0f} px")

    def _mover(self, chave, v):
        if chave == "sens" and protecao.restrito_ativo():
            minimo = (1.6 - self.cfg["limiar_bloqueio"]) * 100
            if v < minimo:
                self.sliders[chave][0].set(minimo)
                v = minimo
                self.avisar("🔒 Modo restrito: só dá para aumentar a sensibilidade.", LARANJA)
        self._rotulo(chave, v)
        if self._timer_salvar:
            self.after_cancel(self._timer_salvar)
        self._timer_salvar = self.after(700, self._salvar_sliders)

    def _salvar_sliders(self):
        g = {k: s.get() for k, (s, _) in self.sliders.items()}
        self._salvar_cfg(limiar_bloqueio=round(1.6 - g["sens"] / 100, 2),
                         margem=round(g["margem"] / 100, 2), suavizar_px=int(g["suave"]))
        self.avisar("Aplicado ✓", VERDE)

    def _alternar_ligado(self):
        if self.vars["ligado"].get():
            protecao.cancelar_pausa()
            if not protecao.esta_rodando("app"):
                protecao.iniciar_app()
            if protecao.autostart_ativo() and not protecao.esta_rodando("guardiao"):
                protecao.iniciar_guardiao()
            self.avisar("Ligando…", VERDE)
            return
        self.vars["ligado"].set(True)
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: não dá para pausar.", LARANJA)
            return
        opcoes = [("15 min", 15), ("30 min", 30), ("1 hora", 60), ("2 horas", 120),
                  ("Até eu ligar", 60 * 24 * 365)]
        self._escolher("Pausar a proteção", "Por quanto tempo?", opcoes, self._pausar)

    def _pausar(self, minutos):
        if protecao.pausar(minutos):
            protecao.parar_app()
            self.vars["ligado"].set(False)
            self.avisar("Pausado.", LARANJA)

    def restrito(self):
        ativo = protecao.restrito_ativo()
        opcoes = [("1 hora", 60), ("4 horas", 240), ("1 dia", 1440), ("3 dias", 4320),
                  ("1 semana", 10080)]
        texto = ("Até o fim do tempo não será possível pausar, desligar proteções,\n"
                 "diminuir a sensibilidade nem desligar o app. Não dá para cancelar.")
        self._escolher("Estender modo restrito" if ativo else "Ativar modo restrito",
                       texto, opcoes, self._ativar_restrito, perigo=True)

    def _ativar_restrito(self, minutos):
        ate = protecao.ativar_restrito(minutos)
        # garante que está tudo ligado e voltando sozinho
        if not protecao.esta_rodando("app"):
            protecao.iniciar_app()
        if not protecao.autostart_ativo():
            protecao.autostart(True)
            self.vars["autostart"].set(True)
        if not protecao.esta_rodando("guardiao"):
            protecao.iniciar_guardiao()
        self.avisar("🔒 Modo restrito até " + time.strftime("%d/%m %H:%M", time.localtime(ate)), ACENTO)

    def editar_sites(self):
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: a lista não pode ser editada agora.", LARANJA)
            return
        self._abrir(config.caminho(self.cfg["sites_bloqueados"]))
        self.avisar("Salve o arquivo e desligue/ligue \"Sites adultos\" para aplicar.", ACENTO, 10)

    def desligar_tudo(self):
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: não dá para desligar.", LARANJA)
            return
        self._escolher("Desligar tudo?",
                       "Para o bloqueador, tira do início do Windows e remove\n"
                       "o bloqueio de sites e a proteção forte.",
                       [("Desligar tudo", 1)], lambda _: self._desligar(), perigo=True)

    def _desligar(self):
        protecao.pausar(60 * 24 * 365)
        protecao.autostart(False)
        self.vars["autostart"].set(False)
        acoes = []
        if sites.secao_atual():
            acoes.append("hosts_remover")
        if protecao.tarefa_existe():
            acoes.append("tarefa_remover")
        for p in protecao.processos():
            try:
                p.kill()
            except Exception:
                pass
        if acoes:
            self._admin(acoes, lambda: None)
        self.vars["forte"].set(False)
        self.avisar("Tudo desligado. Para voltar, ligue a chave lá em cima.", LARANJA, 10)

    # ================= janelas =================
    def _escolher(self, titulo, texto, opcoes, ao_escolher, perigo=False):
        if self.popup and self.popup.winfo_exists():
            self.popup.focus()
            return
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title(titulo)
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        ctk.CTkLabel(j, text=titulo, font=fonte(17, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(j, text=texto, font=fonte(12), text_color=TEXTO2,
                     justify="left").pack(anchor="w", padx=20)
        f = ctk.CTkFrame(j, fg_color="transparent")
        f.pack(padx=16, pady=14)
        cor, hover = (VERMELHO, ("#B91C1C", "#DC2626")) if perigo else (ACENTO, ACENTO_HOVER)
        for i, (txt, valor) in enumerate(opcoes):
            ctk.CTkButton(f, text=txt, width=96, height=36, corner_radius=10, fg_color=cor,
                          hover_color=hover, font=fonte(12, "bold"),
                          command=lambda v=valor: (j.destroy(), ao_escolher(v))
                          ).grid(row=i // 3, column=i % 3, padx=4, pady=4)
        ctk.CTkButton(j, text="Cancelar", fg_color="transparent", text_color=TEXTO2,
                      hover_color=BORDA, command=j.destroy).pack(pady=(0, 14))
        centralizar(j, self)
        j.after(100, j.grab_set)

    def boas_vindas(self):
        if self.popup and self.popup.winfo_exists():
            return
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title("Bem-vindo")
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        img = ctk.CTkImage(Image.open(os.path.join(config.APP, "recursos", "icone.png")), size=(72, 72))
        ctk.CTkLabel(j, image=img, text="").pack(pady=(22, 6))
        ctk.CTkLabel(j, text="Bem-vindo ao Bloqueador de Tela", font=fonte(19, "bold")).pack()
        lista = ctk.CTkFrame(j, fg_color="transparent")
        lista.pack(padx=28, pady=10, anchor="w")
        for ic, txt in (("🖼️", "Cobre nudez em qualquer app com mosaico"),
                        ("🌐", "Bloqueia sites adultos e força a busca segura"),
                        ("🔒", "Modo restrito: trava tudo por um tempo"),
                        ("💻", "Tudo roda no seu PC; nada é enviado")):
            linha = ctk.CTkFrame(lista, fg_color="transparent")
            linha.pack(anchor="w")
            emoji(linha, ic, 15, 30).pack(side="left")
            ctk.CTkLabel(linha, text=txt, font=fonte(13)).pack(side="left", padx=(4, 0))
        ctk.CTkLabel(j, text="Onde você quer o atalho?", font=fonte(14, "bold")).pack(anchor="w", padx=28)
        opcoes = {}
        for chave, txt in (("barra", "Barra de tarefas"), ("desktop", "Área de trabalho"),
                           ("iniciar", "Menu Iniciar")):
            opcoes[chave] = ctk.BooleanVar(value=True)
            ctk.CTkCheckBox(j, text=txt, variable=opcoes[chave], font=fonte(13),
                            fg_color=ACENTO, hover_color=ACENTO_HOVER).pack(anchor="w", padx=32, pady=3)

        def comecar():
            feito = []
            try:
                if opcoes["iniciar"].get() or opcoes["barra"].get():
                    atalhos.criar(atalhos.menu_iniciar())   # a barra usa este atalho
                    feito.append("Menu Iniciar")
                if opcoes["desktop"].get():
                    atalhos.criar(atalhos.desktop())
                    feito.append("Área de trabalho")
            except Exception as e:
                self.avisar(f"Não consegui criar o atalho: {e}", VERMELHO, 10)
            with open(ARQ_BOAS_VINDAS, "w", encoding="utf-8") as f:
                json.dump({"quando": time.time(), "atalhos": feito}, f)
            j.destroy()
            if opcoes["barra"].get():
                self._dica_barra()
            elif feito:
                self.avisar("Atalho criado: " + ", ".join(feito) + " ✓", VERDE)

        ctk.CTkButton(j, text="Começar", height=40, corner_radius=12, fg_color=ACENTO,
                      hover_color=ACENTO_HOVER, font=fonte(14, "bold"),
                      command=comecar).pack(fill="x", padx=28, pady=(14, 22))
        centralizar(j, self)
        j.after(100, j.grab_set)

    def _dica_barra(self):
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title("Fixar na barra de tarefas")
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        ctk.CTkLabel(j, text="Falta 1 clique 📌", font=fonte(18, "bold")).pack(anchor="w", padx=22, pady=(18, 4))
        ctk.CTkLabel(j, text="O Windows não deixa programas se fixarem sozinhos.\n\n"
                             "1. Olhe a barra de tarefas (embaixo): o ícone do escudo\n"
                             "    deste painel está lá.\n"
                             "2. Clique nele com o botão direito.\n"
                             "3. Escolha \"Fixar na barra de tarefas\".",
                     font=fonte(13), justify="left").pack(anchor="w", padx=22)
        ctk.CTkButton(j, text="Entendi", height=36, corner_radius=10, fg_color=ACENTO,
                      hover_color=ACENTO_HOVER, command=j.destroy).pack(fill="x", padx=22, pady=18)
        centralizar(j, self)

    # ================= status (a cada 1 s) =================
    def _status(self):
        try:
            with open(os.path.join(config.DADOS, "status.json"), encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
        rodando = protecao.esta_rodando("app") and time.time() - st.get("atualizado", 0) < 8 \
            and psutil.pid_exists(st.get("pid", -1))
        pausa = protecao.pausa_ate()
        if rodando:
            cor, txt = VERDE, "Protegido"
            disp = st.get("dispositivo", "?").replace("DmlExecutionProvider", "GPU") \
                .replace("CUDAExecutionProvider", "GPU").replace("CPUExecutionProvider", "CPU")
            info = f"Analisando a tela · {disp} · {st.get('analises_s', 0)} por segundo"
            if st.get("bloqueando"):
                info = "Cobrindo conteúdo agora"
        elif pausa:
            cor, txt = LARANJA, "Pausado"
            info = "Volta sozinho às " + time.strftime("%H:%M", time.localtime(pausa)) \
                if pausa - time.time() < 86400 else "Ligue a chave para voltar"
        elif protecao.esta_rodando("app"):
            cor, txt, info = LARANJA, "Iniciando…", "Carregando os modelos de IA"
        else:
            cor, txt, info = VERMELHO, "Desligado", "Ligue a chave para proteger"
        self.lb_estado.configure(text=txt, text_color=cor)
        self.lb_info.configure(text=info)
        ult = st.get("ultimo_bloqueio", "")
        self.lb_ultimo.configure(text=f"Último bloqueio: {ult[:8]}" if ult else "Nenhum bloqueio ainda")
        if not (self.popup and self.popup.winfo_exists()):
            self.vars["ligado"].set(rodando or (not pausa and protecao.esta_rodando("app")))

        ate = protecao.restrito_ate()
        if ate:
            self.lb_restrito.configure(
                text=f"Ativo até {time.strftime('%d/%m às %H:%M', time.localtime(ate))} "
                     f"(faltam {falta(ate)}). Só dá para deixar mais rígido.",
                text_color=ACENTO)
            self.bt_restrito.configure(text="Estender")
        else:
            self.lb_restrito.configure(
                text="Trava tudo por um tempo: ninguém consegue pausar nem desligar, nem você.",
                text_color=TEXTO2)
            self.bt_restrito.configure(text="Ativar")
        estado = "disabled" if ate else "normal"
        self.sw_ligado.configure(state=estado)
        self.bt_desligar.configure(state=estado)
        self.bt_lista.configure(state=estado)
        self.after(1000, self._status)


if __name__ == "__main__":
    os.chdir(config.PASTA)
    try:  # ícone próprio na barra de tarefas (e fixar abre o painel, não o Python)
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(atalhos.APP_ID)
    except Exception:
        pass
    if protecao.instancia_unica("painel"):
        ctk.set_appearance_mode("system")
        Painel().mainloop()
    else:  # já aberto: traz para a frente
        h = ctypes.windll.user32.FindWindowW(None, "Bloqueador de Tela")
        if h:
            ctypes.windll.user32.ShowWindow(h, 9)
            ctypes.windll.user32.SetForegroundWindow(h)
