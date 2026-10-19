"""Painel do Bloqueador de Tela.

Tudo se aplica na hora (sem botão salvar). Modo restrito: por um prazo ou sem
prazo (sai só pedindo desbloqueio e esperando) não dá para pausar nem desligar
nada, só deixar mais rígido.
"""
import copy
import ctypes
import json
import os
import re
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


def hora_valida(s):
    """True se `s` é um horário "HH:MM" válido (00:00 a 23:59)."""
    return bool(re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", (s or "").strip()))


def dur(minutos):
    """Minutos -> texto curto: '30 min', '2 h', '1 dia'."""
    m = int(minutos)
    if m < 60:
        return f"{m} min"
    if m % 1440 == 0:
        d = m // 1440
        return f"{d} dia" + ("s" if d > 1 else "")
    if m % 60 == 0:
        return f"{m // 60} h"
    return f"{m // 60} h {m % 60} min"


def falta(ate):
    s = int(ate - time.time())
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m = s // 60
    if d:
        return f"{d}d {h}h"
    return f"{h}h {m:02d}min" if h else f"{m} min"


# textos do botão "?" de cada função: (título, [(subtítulo, texto), ...])
INFO = {
    "imagens": ("🖼️ Imagens e vídeos", [
        ("Como funciona",
         "Várias vezes por segundo o app tira uma \"foto\" da tela (só na memória: nunca "
         "salva nem envia). Dois modelos de IA olham essa foto: um procura partes do corpo "
         "(seios, nádegas, genitália) e outro dá uma nota de \"conteúdo adulto\" para cada "
         "imagem ou vídeo."),
        ("Quando bloqueia",
         "As notas são somadas. Se passar do limite da Sensibilidade, aquela imagem é "
         "coberta com mosaico (ou a tela toda, se você escolheu \"Tela inteira\"). "
         "Homens sem camisa, como lutadores, não bloqueiam sozinhos: precisa de um "
         "sinal de corpo feminino ou de genitália."),
        ("Onde vale",
         "Em qualquer programa: navegador, Discord, visualizador de fotos, vídeos. "
         "Usa a placa de vídeo se tiver; senão, o processador."),
    ]),
    "sites": ("🌐 Sites adultos", [
        ("Como funciona",
         "Usa o arquivo \"hosts\" do Windows, uma lista que o PC consulta antes de ir "
         "para a internet. Os sites da lista são apontados para lugar nenhum, então "
         "nem chegam a carregar."),
        ("Onde vale",
         "Em todos os navegadores, inclusive aba anônima. A lista fica em "
         "dados/sites_bloqueados.txt (botão \"Editar lista\"); depois de editar, "
         "desligue e ligue esta opção para aplicar."),
        ("Permissão", "Ligar ou desligar pede a permissão de administrador do Windows."),
    ]),
    "safesearch": ("🔎 Busca segura", [
        ("Como funciona",
         "Pelo mesmo arquivo \"hosts\", o Google, o Bing e o DuckDuckGo passam a abrir "
         "sempre na versão com SafeSearch travado."),
        ("Na prática",
         "Imagens e links explícitos somem dos resultados, inclusive do Google Imagens, "
         "mesmo que alguém tente desligar o SafeSearch nas configurações do site."),
        ("Permissão", "Ligar ou desligar pede a permissão de administrador do Windows."),
    ]),
    "titulo": ("🏷️ Palavras no título da aba", [
        ("Como funciona",
         "O app lê o nome da aba ativa de cada janela do navegador (o texto que aparece "
         "na aba). Se tiver uma palavra proibida, as imagens daquela janela passam a ser "
         "cobertas com muito menos (fotos \"quase\", de biquíni, sugestivas)."),
        ("Só palavra não cobre",
         "Uma página só com texto nunca é coberta: precisa ter imagem. Imagem explícita "
         "é coberta sempre, com ou sem palavra."),
        ("Palavra inteira",
         "Só conta a palavra inteira (ou no plural): um erro de digitação como "
         "\"pornomes\" não bloqueia."),
        ("Para não te prender",
         "A faixa das abas e o botão X ficam livres, para você fechar a aba."),
        ("Onde vale",
         "Só no navegador. Uma mensagem com a palavra no WhatsApp ou no Discord "
         "(aplicativos) não bloqueia."),
    ]),
    "ocr": ("📝 Texto na página", [
        ("Como funciona",
         "A cada 2 segundos o leitor de texto do próprio Windows lê o que está escrito "
         "na janela do navegador ativa. Se aparecer uma palavra proibida, as imagens "
         "daquela página passam a ser cobertas com muito menos, até você mudar de página. "
         "O texto sozinho não cobre nada."),
        ("Onde vale",
         "Só dentro da janela do navegador. Editores de texto, terminal e o próprio "
         "log do app são ignorados."),
    ]),
    "rapido": ("⚡ Bloqueio rápido", [
        ("Para quê",
         "Para a hora em que bate a vontade: um clique e pronto, sem perguntas. Liga o "
         "Modo restrito por 30 minutos e todas as proteções (imagens, título e texto)."),
        ("O que trava",
         "Até acabar não dá para pausar, desligar nem baixar a sensibilidade. Os arquivos "
         "do app ficam \"em uso\": o Windows não deixa apagar a pasta."),
        ("Sem abrir o painel", "Atalho: Ctrl + Alt + Shift + B."),
    ]),
    "previas": ("🪟 Esconder prévias", [
        ("Por quê",
         "A miniatura que aparece ao passar o mouse no ícone do Chrome na barra de "
         "tarefas, as do Alt+Tab e o \"Espiar\" (passar o mouse no nome da janela e ela "
         "aparecer inteira) são desenhados pelo Windows acima de qualquer programa: o "
         "mosaico não consegue cobrir."),
        ("O que muda",
         "A miniatura da barra não aparece mais (só a lista com os nomes), o \"Espiar\" "
         "desliga e o Alt+Tab fica no estilo clássico, só com os ícones. Ao ligar ou "
         "desligar, a barra de tarefas pisca (o Windows "
         "reinicia o Explorer) e as pastas abertas fecham."),
    ]),
    "shorts": ("📵 Vídeos curtos", [
        ("O que faz",
         "Remove os vídeos curtos da página (não cobre com mosaico): os Shorts do "
         "YouTube, os Reels do Instagram e o feed \"Para Você\" do TikTok. No YouTube, "
         "abrir um Short vira um vídeo normal; no Instagram, a página de Reels volta "
         "para a home."),
        ("Precisa instalar a extensão",
         "Isso só uma extensão de navegador consegue fazer. Clique em \"Instalar\", siga "
         "os 3 passos (uma vez só) e pronto; o liga/desliga continua sendo aqui no "
         "Painel. Funciona no Chrome, Edge e Brave."),
        ("Onde não vale",
         "Em outros navegadores (Firefox, Opera) a extensão não é instalada. O resto do "
         "app continua funcionando normalmente neles."),
    ]),
    "lembrete": ("⏰ Lembrete de pausa", [
        ("Como funciona",
         "Depois do tempo escolhido usando o PC sem parar, aparece um aviso no canto da "
         "tela para você dar uma pausa."),
        ("O que conta como pausa",
         "Ficar 5 minutos sem mexer no mouse nem no teclado zera a contagem."),
    ]),
    "restrito": ("🔒 Modo restrito", [
        ("Como funciona",
         "Você escolhe por quanto tempo (1 hora a 1 semana) ou \"Sem prazo\". Até acabar "
         "não dá para pausar, desligar proteções, baixar a sensibilidade, editar a lista "
         "de sites nem desligar o app, nem pelo painel nem pelo atalho de teclado."),
        ("Sem prazo",
         "Não tem hora para acabar. Ao ligar, você escolhe quanto o desbloqueio vai "
         "demorar (5 min, 2 horas, ou o que quiser). Para sair, toca em \"Desbloquear\" e "
         "espera esse tempo com tudo ainda travado — dá tempo de a vontade passar. Pode "
         "cancelar a espera a qualquer momento. É o jeito mais firme, como o ScreenZen."),
        ("O que ainda dá",
         "Deixar mais rígido: ligar proteções, aumentar a sensibilidade, estender o tempo "
         "ou aumentar a espera de desbloqueio."),
        ("Atenção", "Com prazo não tem como cancelar antes. Comece com 1 hora para conhecer."),
    ]),
    "horario": ("🌙 Modo horário", [
        ("Como funciona",
         "Liga o Modo restrito sozinho todo dia dentro da faixa de horas que você escolher "
         "(ex.: 23:00 às 06:00). Enquanto a faixa dura, vale tudo do Modo restrito: não dá "
         "para pausar nem desligar. Fora dela, volta ao normal."),
        ("Por que usar",
         "Para travar de madrugada ou nos horários em que você costuma cair em tentação, "
         "sem precisar lembrar de ligar."),
        ("Offline", "Usa só o relógio do PC; não precisa de internet."),
    ]),
    "excecoes": ("🎮 Exceções", [
        ("Como funciona",
         "Lista de apps ou janelas em que o bloqueador não cobre nada enquanto estão em "
         "primeiro plano. Casa por um pedaço do título da janela ou pelo nome do programa "
         "(.exe)."),
        ("Para que serve",
         "Para transmissões de luta (UFC), jogos em tela cheia e afins, que às vezes a IA "
         "cobre por engano. Ex.: \"ea sports ufc\", \"eldenring.exe\", \"vlc.exe\"."),
        ("Cuidado",
         "O que estiver na lista fica totalmente liberado; use só com o que você confia. "
         "No Modo restrito a lista não pode ser alterada."),
    ]),
    "forte": ("🛡️ Proteção forte", [
        ("Como funciona",
         "Cria uma tarefa no Agendador do Windows que, a cada minuto, confere se o "
         "bloqueador está aberto e o reabre se não estiver."),
        ("Por que usar",
         "Sem ela, se alguém fechar o app e o processo vigia pelo Gerenciador de "
         "Tarefas, ele só volta no próximo login. Com ela, volta em até 1 minuto. "
         "Combina bem com o Modo restrito."),
        ("Permissão", "Ligar ou desligar pede a permissão de administrador do Windows."),
    ]),
}


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
        self._cartao_travas()
        self._cartao_bloquear()
        self._cartao_cobrir()
        self._cartao_bem_estar()
        self._cartao_sistema()
        ctk.CTkLabel(self.corpo, text="Pausar: Ctrl + Alt + Shift + Q · Bloqueio rápido: Ctrl + Alt + Shift + B",
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
                     justify="left", wraplength=300).pack(fill="x")
        var = ctk.BooleanVar(value=valor)
        sw = ctk.CTkSwitch(f, text="", variable=var, width=46, progress_color=ACENTO,
                           command=lambda: comando(chave))
        sw.pack(side="right")
        if chave in INFO:
            self._bt_info(f, chave).pack(side="right", padx=(0, 6))
        self.vars[chave], self.switches[chave] = var, sw
        return f

    def _bt_info(self, pai, chave):
        return ctk.CTkButton(pai, text="?", width=26, height=26, corner_radius=13,
                             fg_color="transparent", border_width=1, border_color=BORDA,
                             text_color=TEXTO2, hover_color=BORDA, font=fonte(12, "bold"),
                             command=lambda: self.explicar(chave))

    def _cartao_travas(self):
        c = self._cartao("Travas", "Para não conseguir desligar num momento de fraqueza.")
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=16, pady=(10, 2))
        self.bt_rapido = ctk.CTkButton(f, text="⚡  Bloqueio rápido", height=44, corner_radius=12,
                                       fg_color=VERMELHO, hover_color=("#B91C1C", "#DC2626"),
                                       font=fonte(15, "bold"), command=self.bloqueio_rapido)
        self.bt_rapido.pack(side="left", fill="x", expand=True)
        self._bt_info(f, "rapido").pack(side="right", padx=(8, 0))
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=(8, 5))
        emoji(f, "🔒").pack(side="left")
        t = ctk.CTkFrame(f, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ctk.CTkLabel(t, text="Modo restrito", font=fonte(13, "bold"), anchor="w").pack(fill="x")
        self.lb_restrito = ctk.CTkLabel(t, text="", font=fonte(11), text_color=TEXTO2,
                                        anchor="w", justify="left", wraplength=260)
        self.lb_restrito.pack(fill="x")
        self.bt_restrito = ctk.CTkButton(f, text="Ativar", width=84, height=32, corner_radius=10,
                                         fg_color=ACENTO, hover_color=ACENTO_HOVER,
                                         font=fonte(12, "bold"), command=self.restrito)
        self.bt_restrito.pack(side="right")
        self._bt_info(f, "restrito").pack(side="right", padx=(0, 6))
        # modo horário: liga o Modo restrito sozinho numa faixa de horas
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=(2, 5))
        emoji(f, "🌙").pack(side="left")
        t = ctk.CTkFrame(f, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ctk.CTkLabel(t, text="Modo horário", font=fonte(13, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(t, text="Liga o Modo restrito sozinho nesta faixa de horas",
                     font=fonte(11), text_color=TEXTO2, anchor="w", justify="left",
                     wraplength=200).pack(fill="x")
        hr = self.cfg["horario_restrito"]
        var = ctk.BooleanVar(value=hr["ativo"])
        sw = ctk.CTkSwitch(f, text="", variable=var, width=46, progress_color=ACENTO,
                           command=self._alternar_horario)
        sw.pack(side="right")
        self._bt_info(f, "horario").pack(side="right", padx=(0, 6))
        self.ent_fim = ctk.CTkEntry(f, width=52, height=28, justify="center", font=fonte(12))
        self.ent_fim.insert(0, hr["fim"])
        self.ent_fim.pack(side="right", padx=(0, 6))
        ctk.CTkLabel(f, text="às", font=fonte(11), text_color=TEXTO2).pack(side="right", padx=2)
        self.ent_ini = ctk.CTkEntry(f, width=52, height=28, justify="center", font=fonte(12))
        self.ent_ini.insert(0, hr["inicio"])
        self.ent_ini.pack(side="right")
        self.vars["horario"] = var
        for e in (self.ent_ini, self.ent_fim):
            e.bind("<FocusOut>", lambda _e: self._salvar_horario())
            e.bind("<Return>", lambda _e: self._salvar_horario())
        self._linha(c, "🛡️", "Proteção forte", "O Windows reabre o app em até 1 min se fecharem",
                    "forte", protecao.tarefa_existe(), self._alternar)
        ctk.CTkFrame(c, fg_color="transparent", height=6).pack()

    def _cartao_bloquear(self):
        c = self._cartao("O que bloquear", "Clique no ? para ver como cada um funciona.")
        cfg = self.cfg
        self._linha(c, "🖼️", "Imagens e vídeos", "IA olha a tela e cobre nudez em qualquer app",
                    "imagens", "nudez" in cfg["detectores"], self._alternar)
        linha = self._linha(c, "🌐", "Sites adultos", "Sites da lista nem carregam, em todo navegador",
                            "sites", cfg["bloquear_sites"], self._alternar)
        self.bt_lista = ctk.CTkButton(linha, text="Editar lista", width=96, height=26,
                                      fg_color="transparent", border_width=1, border_color=BORDA,
                                      text_color=ACENTO, hover_color=BORDA, font=fonte(11),
                                      command=self.editar_sites)
        self.bt_lista.pack(side="right", padx=(0, 6))
        self._linha(c, "🔎", "Busca segura", "Resultados explícitos somem do Google, Bing e DuckDuckGo",
                    "safesearch", cfg["forcar_safesearch"], self._alternar)
        self._linha(c, "🏷️", "Palavras no título da aba", "Aba com nome proibido: imagens cobertas com menos",
                    "titulo", cfg["titulo_ativo"], self._alternar)
        self._linha(c, "📝", "Texto na página", "Palavra na página: imagens cobertas com menos",
                    "ocr", cfg["ocr"]["ativo"], self._alternar)
        self._linha(c, "🪟", "Esconder prévias", "Sem miniatura das janelas na barra e no Alt+Tab",
                    "previas", cfg["esconder_previas"], self._alternar)
        linha = self._linha(c, "📵", "Vídeos curtos", "Remove Shorts, Reels e o feed do TikTok da página",
                            "shorts", cfg["bloquear_shorts"], self._alternar)
        self.bt_extensao = ctk.CTkButton(linha, text="Instalar", width=90, height=26,
                                         fg_color="transparent", border_width=1, border_color=BORDA,
                                         text_color=ACENTO, hover_color=BORDA, font=fonte(11),
                                         command=self.instalar_extensao)
        self.bt_extensao.pack(side="right", padx=(0, 6))
        # exceções: apps/janelas onde nada é coberto
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=12, pady=5)
        emoji(f, "🎮").pack(side="left")
        t = ctk.CTkFrame(f, fg_color="transparent")
        t.pack(side="left", fill="x", expand=True, padx=(4, 8))
        ctk.CTkLabel(t, text="Exceções", font=fonte(13, "bold"), anchor="w").pack(fill="x")
        ctk.CTkLabel(t, text="Apps/janelas onde o app não cobre nada (UFC, jogos)",
                     font=fonte(11), text_color=TEXTO2, anchor="w", justify="left",
                     wraplength=280).pack(fill="x")
        self.bt_excecoes = ctk.CTkButton(f, text="Editar", width=90, height=26,
                                         fg_color="transparent", border_width=1, border_color=BORDA,
                                         text_color=ACENTO, hover_color=BORDA, font=fonte(11),
                                         command=self.editar_excecoes)
        self.bt_excecoes.pack(side="right", padx=(0, 6))
        self._bt_info(f, "excecoes").pack(side="right", padx=(0, 6))
        ctk.CTkFrame(c, fg_color="transparent", height=6).pack()

    def _cartao_cobrir(self):
        c = self._cartao("Como cobrir")
        self.seg_modo = ctk.CTkSegmentedButton(
            c, values=["Só a área", "Tela inteira"], font=fonte(13), height=34,
            selected_color=ACENTO, selected_hover_color=ACENTO_HOVER, command=self._mudar_modo)
        self.seg_modo.pack(fill="x", padx=16, pady=(10, 8))

        self.sliders = {}
        itens = [
            ("sens", "Sensibilidade", 0, 100),
            ("margem", "Área extra em volta", 0, 100),
            ("suave", "Borda suave", 0, 120),
        ]
        for chave, titulo, a, b in itens:
            f = ctk.CTkFrame(c, fg_color="transparent")
            f.pack(fill="x", padx=16, pady=(4, 0))
            ctk.CTkLabel(f, text=titulo, font=fonte(13)).pack(side="left")
            lb = ctk.CTkLabel(f, text="", font=fonte(12, "bold"), text_color=ACENTO)
            lb.pack(side="right")
            s = ctk.CTkSlider(c, from_=a, to=b, progress_color=ACENTO, button_color=ACENTO,
                              button_hover_color=ACENTO_HOVER,
                              command=lambda v, k=chave: self._mover(k, v))
            # roda do mouse só rola a página; o slider muda só arrastando
            s._canvas.unbind("<MouseWheel>")
            s.pack(fill="x", padx=16, pady=(2, 6))
            self.sliders[chave] = (s, lb)
        self._mostrar_cobrir()
        ctk.CTkFrame(c, fg_color="transparent", height=6).pack()

    def _mostrar_cobrir(self):
        cfg = self.cfg
        self.seg_modo.set("Tela inteira" if cfg["modo"] == "tela" else "Só a área")
        valores = {"sens": (1.6 - cfg["limiar_bloqueio"]) * 100, "margem": cfg["margem"] * 100,
                   "suave": cfg["suavizar_px"]}
        for chave, v in valores.items():
            self.sliders[chave][0].set(v)
            self._rotulo(chave, v)

    def _cartao_bem_estar(self):
        c = self._cartao("Bem-estar")
        lp = self.cfg["lembrete_pausa"]
        linha = self._linha(c, "⏰", "Lembrete de pausa", "Avisa quando é hora de levantar um pouco",
                            "lembrete", lp["ativo"], self._alternar)
        self.seg_lembrete = ctk.CTkSegmentedButton(
            c, values=["25 min", "45 min", "60 min", "90 min"], font=fonte(12), height=30,
            selected_color=ACENTO, selected_hover_color=ACENTO_HOVER, command=self._mudar_lembrete)
        self.seg_lembrete.set(f"{lp['minutos']} min")
        self.seg_lembrete.pack(fill="x", padx=16, pady=(2, 14))

    def _mudar_lembrete(self, valor):
        cfg = config.carregar()
        cfg["lembrete_pausa"]["minutos"] = int(valor.split()[0])
        config.salvar(cfg)
        self.cfg = cfg
        self.avisar("Aplicado ✓", VERDE)

    def _alternar_horario(self):
        if protecao.restrito_ativo() and not self.vars["horario"].get():
            self.vars["horario"].set(True)
            self.avisar("🔒 Modo restrito: não dá para desligar o modo horário.", LARANJA)
            return
        self._salvar_horario()

    def _salvar_horario(self):
        ini, fim = self.ent_ini.get().strip(), self.ent_fim.get().strip()
        if not (hora_valida(ini) and hora_valida(fim)):
            self.avisar("Horário inválido. Use HH:MM (ex.: 23:00).", VERMELHO, 8)
            return
        novo = {"ativo": bool(self.vars["horario"].get()), "inicio": ini, "fim": fim}
        if novo == self.cfg.get("horario_restrito"):
            return  # nada mudou (ex.: só saiu do campo): não salva nem avisa à toa
        cfg = config.carregar()
        cfg["horario_restrito"] = novo
        config.salvar(cfg)
        self.cfg = cfg
        self.avisar("Aplicado ✓", VERDE)

    def editar_excecoes(self):
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: a lista de exceções não pode mudar agora.", LARANJA)
            return
        if self.popup and self.popup.winfo_exists():
            self.popup.focus()
            return
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title("Exceções")
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        ctk.CTkLabel(j, text="Exceções", font=fonte(17, "bold")).pack(anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(j, text="Uma por linha: um pedaço do título da janela ou o nome do .exe.\n"
                     "Enquanto esse app/janela estiver na frente, nada é coberto.\n"
                     "Ex.: ea sports ufc  |  eldenring.exe  |  vlc.exe",
                     font=fonte(12), text_color=TEXTO2, justify="left").pack(anchor="w", padx=20)
        cx = ctk.CTkTextbox(j, width=380, height=150, font=fonte(12))
        cx.pack(padx=20, pady=12, fill="both")
        cx.insert("1.0", "\n".join(self.cfg.get("excecoes", [])))

        def salvar():
            linhas, vistos = [], set()
            for linha in cx.get("1.0", "end").splitlines():
                e = linha.strip().lower()
                if e and e not in vistos:
                    vistos.add(e)
                    linhas.append(e)
            cfg = config.carregar()
            cfg["excecoes"] = linhas
            config.salvar(cfg)
            self.cfg = cfg
            j.destroy()
            self.avisar(f"Exceções salvas ✓ ({len(linhas)})", VERDE)

        ctk.CTkButton(j, text="Salvar", width=100, fg_color=ACENTO, hover_color=ACENTO_HOVER,
                      font=fonte(12, "bold"), command=salvar).pack(pady=(0, 8))
        ctk.CTkButton(j, text="Cancelar", fg_color="transparent", text_color=TEXTO2,
                      hover_color=BORDA, command=j.destroy).pack(pady=(0, 14))
        centralizar(j, self)
        j.after(100, j.grab_set)

    def _cartao_sistema(self):
        c = self._cartao("Sistema")
        self._linha(c, "🚀", "Iniciar com o Windows", "Liga sozinho quando você entra no PC",
                    "autostart", protecao.autostart_ativo(), self._alternar)
        f = ctk.CTkFrame(c, fg_color="transparent")
        f.pack(fill="x", padx=14, pady=(8, 14))
        estilo = dict(height=32, corner_radius=10, fg_color="transparent", border_width=1,
                      border_color=BORDA, text_color=("#111827", "#E5E7EB"), hover_color=BORDA,
                      font=fonte(12))
        ctk.CTkButton(f, text="Ver log", width=74, command=lambda: self._abrir(
            os.path.join(config.PASTA, "logs", "bloqueador.log")), **estilo).pack(side="left", padx=2)
        ctk.CTkButton(f, text="Atalhos…", width=80, command=self.boas_vindas,
                      **estilo).pack(side="left", padx=2)
        self.bt_resetar = ctk.CTkButton(f, text="Restaurar padrão", width=120,
                                        command=self.resetar, **estilo)
        self.bt_resetar.pack(side="left", padx=2)
        estilo.update(text_color=VERMELHO, border_color=VERMELHO)
        self.bt_desligar = ctk.CTkButton(f, text="Desligar tudo", width=100,
                                         command=self.desligar_tudo, **estilo)
        self.bt_desligar.pack(side="right", padx=2)

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
        if protecao.restrito_ativo() and not novo and chave != "lembrete":
            var.set(True)
            self.avisar("🔒 Modo restrito: só dá para ligar proteções.", LARANJA)
            return
        if chave == "imagens":
            self._salvar_cfg(detectores=["nudez"] if novo else [])
        elif chave == "titulo":
            self._salvar_cfg(titulo_ativo=novo)
        elif chave == "ocr":
            self._salvar_cfg(ocr_ativo=novo)
        elif chave == "previas":
            self._salvar_cfg(esconder_previas=novo)
            self.avisar("Reiniciando a barra de tarefas…", ACENTO)
            threading.Thread(target=protecao.esconder_previas, args=(novo,), daemon=True).start()
            return
        elif chave == "shorts":
            self._salvar_cfg(bloquear_shorts=novo)
            if novo and not protecao.host_curtos_registrado():
                self.avisar("Ligado. Falta instalar a extensão: clique em \"Instalar\".", LARANJA, 10)
            else:
                self.avisar("Aplicado ✓ (recarregue a aba do YouTube/Instagram/TikTok)", VERDE, 8)
            return
        elif chave == "lembrete":
            cfg = config.carregar()
            cfg["lembrete_pausa"]["ativo"] = novo
            config.salvar(cfg)
            self.cfg = cfg
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
        opcoes = [("1 hora", 60), ("4 horas", 240), ("1 dia", 1440),
                  ("1 semana", 10080), ("Sem prazo", "livre")]
        texto = ("Enquanto durar, não dá para pausar, desligar proteções, diminuir\n"
                 "a sensibilidade, apagar nem fechar o app.\n"
                 "\"Sem prazo\" não tem hora para acabar: para sair você pede o\n"
                 "desbloqueio e espera um tempo que você escolhe agora.")
        self._escolher("Estender modo restrito" if ativo else "Ativar modo restrito",
                       texto, opcoes, self._ativar_restrito, perigo=True)

    def _ativar_restrito(self, minutos):
        if minutos == "livre":
            self._ativar_livre()  # abre o seletor do tempo de desbloqueio
            return
        self._pos_ativar_restrito(protecao.ativar_restrito(minutos))

    def _pos_ativar_restrito(self, ate):
        # garante que está tudo ligado e voltando sozinho
        if not protecao.esta_rodando("app"):
            protecao.iniciar_app()
        if not protecao.autostart_ativo():
            protecao.autostart(True)
            self.vars["autostart"].set(True)
        if not protecao.esta_rodando("guardiao"):
            protecao.iniciar_guardiao()
        if ate < protecao.INDEFINIDO:
            self.avisar("🔒 Modo restrito até " + time.strftime("%d/%m %H:%M", time.localtime(ate)),
                        ACENTO)

    def _ativar_livre(self):
        if self.popup and self.popup.winfo_exists():
            self.popup.focus()
            return
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title("Modo restrito sem prazo")
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        ctk.CTkLabel(j, text="Modo restrito sem prazo", font=fonte(17, "bold")).pack(
            anchor="w", padx=20, pady=(18, 2))
        ctk.CTkLabel(j, text="Não tem hora para acabar. Para sair, você vai tocar em\n"
                     "\"Desbloquear\" e esperar o tempo que escolher agora, com tudo\n"
                     "ainda travado. Quanto quer esperar?",
                     font=fonte(12), text_color=TEXTO2, justify="left").pack(anchor="w", padx=20)

        def ativar(espera):
            espera = max(1, int(espera))
            j.destroy()
            self._pos_ativar_restrito(protecao.ativar_restrito_livre(espera))
            self.avisar(f"🔒 Sem prazo. O desbloqueio vai levar {dur(espera)}.", ACENTO, 10)

        f = ctk.CTkFrame(j, fg_color="transparent")
        f.pack(padx=16, pady=(12, 4))
        presets = [("10 min", 10), ("30 min", 30), ("1 hora", 60), ("2 horas", 120),
                   ("4 horas", 240), ("8 horas", 480), ("12 horas", 720), ("1 dia", 1440)]
        for i, (txt, v) in enumerate(presets):
            ctk.CTkButton(f, text=txt, width=96, height=36, corner_radius=10, fg_color=VERMELHO,
                          hover_color=("#B91C1C", "#DC2626"), font=fonte(12, "bold"),
                          command=lambda v=v: ativar(v)).grid(row=i // 3, column=i % 3, padx=4, pady=4)
        g = ctk.CTkFrame(j, fg_color="transparent")
        g.pack(padx=16, pady=(2, 8))
        ctk.CTkLabel(g, text="Outro:", font=fonte(12)).pack(side="left", padx=(0, 6))
        ent = ctk.CTkEntry(g, width=66, height=32, justify="center", font=fonte(12))
        ent.pack(side="left")
        ctk.CTkLabel(g, text="min", font=fonte(12), text_color=TEXTO2).pack(side="left", padx=4)

        def ativar_custom():
            t = ent.get().strip()
            if t.isdigit() and int(t) >= 1:
                ativar(int(t))
            else:
                self.avisar("Digite um número de minutos (1 ou mais).", VERMELHO, 6)

        ent.bind("<Return>", lambda _e: ativar_custom())
        ctk.CTkButton(g, text="Ativar", width=80, height=32, fg_color=ACENTO,
                      hover_color=ACENTO_HOVER, font=fonte(12, "bold"),
                      command=ativar_custom).pack(side="left", padx=6)
        ctk.CTkButton(j, text="Cancelar", fg_color="transparent", text_color=TEXTO2,
                      hover_color=BORDA, command=j.destroy).pack(pady=(0, 14))
        centralizar(j, self)
        j.after(100, j.grab_set)

    def _desbloquear(self):
        espera = self.cfg.get("espera_desbloqueio_min", 30)

        def confirmar(_):
            d = protecao.pedir_desbloqueio()
            if d:
                self.avisar("⏳ Desbloqueio pedido: o modo restrito sai às "
                            + time.strftime("%H:%M", time.localtime(d))
                            + ". Até lá continua travado.", LARANJA, 12)

        self._escolher(
            "Desbloquear o modo restrito",
            f"O modo restrito vai se desligar daqui a {dur(espera)}.\n"
            "Até lá continua tudo travado. Dá para cancelar quando quiser.",
            [(f"Esperar {dur(espera)}", "ok")], confirmar, perigo=True)

    def _cancelar_desbloqueio(self):
        protecao.cancelar_desbloqueio()
        self.avisar("Desbloqueio cancelado: continua travado.", ACENTO)

    def bloqueio_rapido(self):
        ate = protecao.bloqueio_rapido()
        self._ativar_restrito(0)  # garante app, guardião e início com o Windows
        self.cfg = config.carregar()
        for chave in ("imagens", "titulo", "ocr"):
            self.vars[chave].set(True)
        self.avisar("⚡ Travado até " + time.strftime("%H:%M", time.localtime(ate)) +
                    ". Respira: isso passa.", VERMELHO, 15)

    def editar_sites(self):
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: a lista não pode ser editada agora.", LARANJA)
            return
        self._abrir(config.caminho(self.cfg["sites_bloqueados"]))
        self.avisar("Salve o arquivo e desligue/ligue \"Sites adultos\" para aplicar.", ACENTO, 10)

    def instalar_extensao(self):
        try:
            protecao.registrar_host_curtos()
        except Exception as e:
            self.avisar(f"Não consegui preparar a extensão: {e}", VERMELHO, 10)
            return
        protecao.PASTA_EXTENSAO and self._abrir(protecao.PASTA_EXTENSAO)
        self._escolher(
            "Instalar a extensão (uma vez)",
            "Abri a pasta da extensão. No navegador (Chrome, Edge ou Brave):\n\n"
            "1. Abra  chrome://extensions  (ou edge://extensions).\n"
            "2. Ligue o \"Modo do desenvolvedor\" (canto superior direito).\n"
            "3. Clique em \"Carregar sem compactação\" e escolha a pasta\n"
            "    \"extensao\" que acabei de abrir.\n\n"
            "Depois é só manter o interruptor \"Vídeos curtos\" ligado aqui.",
            [("Abrir chrome://extensions", "chrome"), ("Já instalei", "ok")],
            self._pos_instalar)

    def _pos_instalar(self, qual):
        if qual == "chrome":
            try:
                os.startfile("chrome://extensions")
            except OSError:
                self.avisar("Abra chrome://extensions no seu navegador.", ACENTO, 8)
        else:
            self.avisar("Pronto ✓ Recarregue a aba do YouTube/Instagram/TikTok.", VERDE, 8)

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

    def resetar(self):
        if protecao.restrito_ativo():
            self.avisar("🔒 Modo restrito: não dá para restaurar agora.", LARANJA)
            return
        self._escolher("Restaurar padrão?",
                       "Volta \"O que bloquear\" e \"Como cobrir\" para o padrão.\n"
                       "A lista de sites, as travas e o início com o Windows não mudam.",
                       [("Restaurar", 1)], lambda _: self._resetar())

    def _resetar(self):
        padrao = copy.deepcopy(config.PADRAO)
        atual = config.carregar()
        padrao["sites_bloqueados"] = atual["sites_bloqueados"]  # mantém a lista
        padrao["lembrete_pausa"] = atual["lembrete_pausa"]
        padrao["esconder_previas"] = atual["esconder_previas"]  # mexe na barra: não reseta
        padrao["bloquear_shorts"] = atual["bloquear_shorts"]
        padrao["excecoes"] = atual["excecoes"]  # lista do usuário, não reseta
        padrao["horario_restrito"] = atual["horario_restrito"]
        config.salvar(padrao)
        self.cfg = padrao
        self.vars["imagens"].set("nudez" in padrao["detectores"])
        self.vars["titulo"].set(padrao["titulo_ativo"])
        self.vars["ocr"].set(padrao["ocr"]["ativo"])
        self.vars["sites"].set(padrao["bloquear_sites"])
        self.vars["safesearch"].set(padrao["forcar_safesearch"])
        self._mostrar_cobrir()
        desejada = sites.secao_desejada(config.caminho(padrao["sites_bloqueados"]),
                                        padrao["bloquear_sites"], padrao["forcar_safesearch"])
        if desejada != sites.secao_atual():
            self._admin(["hosts_aplicar"], lambda: None)
        else:
            self.avisar("Configurações restauradas ✓", VERDE)

    # ================= janelas =================
    def explicar(self, chave):
        titulo, partes = INFO[chave]
        titulo = titulo.replace("️", "")  # o Tk desenha esse seletor como espaço
        if self.popup and self.popup.winfo_exists():
            self.popup.destroy()
        j = self.popup = ctk.CTkToplevel(self, fg_color=CARTAO)
        j.title(titulo.split(" ", 1)[1])
        j.resizable(False, False)
        j.transient(self)
        por_icone(j)
        ctk.CTkLabel(j, text=titulo, font=fonte(17, "bold")).pack(anchor="w", padx=22, pady=(18, 6))
        for sub, texto in partes:
            ctk.CTkLabel(j, text=sub, font=fonte(13, "bold"), text_color=ACENTO,
                         anchor="w").pack(fill="x", padx=22, pady=(8, 0))
            ctk.CTkLabel(j, text=texto, font=fonte(12), justify="left", anchor="w",
                         wraplength=380).pack(fill="x", padx=22)
        ctk.CTkButton(j, text="Entendi", height=34, corner_radius=10, fg_color=ACENTO,
                      hover_color=ACENTO_HOVER, command=j.destroy).pack(fill="x", padx=22, pady=18)
        centralizar(j, self)
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
        if not ate:
            self.lb_restrito.configure(
                text="Trava tudo por um tempo: ninguém consegue pausar nem desligar, nem você.",
                text_color=TEXTO2)
            self.bt_restrito.configure(text="Ativar", command=self.restrito,
                                       fg_color=ACENTO, hover_color=ACENTO_HOVER)
        elif protecao.restrito_indefinido():
            d = protecao.desbloqueio_em()
            if d:
                self.lb_restrito.configure(
                    text=f"Sem prazo. Desbloqueia em {falta(d)} "
                         f"({time.strftime('%H:%M', time.localtime(d))}). "
                         "Toque em Cancelar para voltar a travar.",
                    text_color=LARANJA)
                self.bt_restrito.configure(text="Cancelar", command=self._cancelar_desbloqueio,
                                           fg_color=ACENTO, hover_color=ACENTO_HOVER)
            else:
                self.lb_restrito.configure(
                    text="Ativo sem prazo. Para sair, peça o desbloqueio e espere "
                         f"{dur(self.cfg.get('espera_desbloqueio_min', 30))}.",
                    text_color=ACENTO)
                self.bt_restrito.configure(text="Desbloquear", command=self._desbloquear,
                                           fg_color=VERMELHO, hover_color=("#B91C1C", "#DC2626"))
        else:
            self.lb_restrito.configure(
                text=f"Ativo até {time.strftime('%d/%m às %H:%M', time.localtime(ate))} "
                     f"(faltam {falta(ate)}). Só dá para deixar mais rígido.",
                text_color=ACENTO)
            self.bt_restrito.configure(text="Estender", command=self.restrito,
                                       fg_color=ACENTO, hover_color=ACENTO_HOVER)
        estado = "disabled" if ate else "normal"
        self.sw_ligado.configure(state=estado)
        self.bt_desligar.configure(state=estado)
        self.bt_lista.configure(state=estado)
        self.bt_resetar.configure(state=estado)
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
