"""Painel do Bloqueador de Tela: status, liga/desliga das proteções,
sensibilidade, senha, pausa e lista de sites."""
import ctypes
import json
import os
import time
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

import psutil

from bloqueador import config, protecao, sites

COR_ATIVO, COR_PAUSA, COR_OFF = "#1f9d55", "#d97706", "#c53030"


def pedir_senha(pai, titulo="Senha", texto="Digite a senha:"):
    return simpledialog.askstring(titulo, texto, show="*", parent=pai)


class Painel:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Bloqueador de Tela")
        self.root.resizable(False, False)
        estilo = ttk.Style()
        if "vista" in estilo.theme_names():
            estilo.theme_use("vista")
        estilo.configure("Titulo.TLabel", font=("Segoe UI", 15, "bold"))
        estilo.configure("Status.TLabel", font=("Segoe UI", 12, "bold"))
        estilo.configure("Info.TLabel", foreground="#555")

        self.cfg = config.carregar()
        self.desbloqueado = not protecao.tem_senha()
        self.controles = []
        self._montar()
        self._carregar_valores()
        self._aplicar_trava()
        self._status()

    # ---------------- montagem ----------------
    def _montar(self):
        r = ttk.Frame(self.root, padding=14)
        r.grid()

        topo = ttk.Frame(r)
        topo.grid(sticky="ew")
        ttk.Label(topo, text="Bloqueador de Tela", style="Titulo.TLabel").grid(row=0, column=0, sticky="w")
        self.bt_trava = ttk.Button(topo, command=self._alternar_trava, width=16)
        self.bt_trava.grid(row=0, column=1, sticky="e", padx=(40, 0))
        topo.columnconfigure(0, weight=1)

        st = ttk.Frame(r, padding=(0, 8))
        st.grid(sticky="ew")
        self.lb_bola = tk.Label(st, text="●", font=("Segoe UI", 18))
        self.lb_bola.grid(row=0, column=0, rowspan=2, padx=(0, 6))
        self.lb_status = ttk.Label(st, style="Status.TLabel")
        self.lb_status.grid(row=0, column=1, sticky="w")
        self.lb_info = ttk.Label(st, style="Info.TLabel")
        self.lb_info.grid(row=1, column=1, sticky="w")
        self.lb_ultimo = ttk.Label(r, style="Info.TLabel")
        self.lb_ultimo.grid(sticky="w")

        # proteções
        pf = ttk.LabelFrame(r, text=" Proteções ", padding=10)
        pf.grid(sticky="ew", pady=(10, 0))
        self.v = {k: tk.BooleanVar() for k in
                  ("imagens", "titulo", "ocr", "sites", "safesearch", "autostart", "forte")}
        itens = [
            ("imagens", "Detecção de imagens por IA (nudez)", "Analisa a tela com 2 modelos locais"),
            ("titulo", "Palavras no título da aba", "Só quando a janela ativa é navegador"),
            ("ocr", "Texto visível na página (OCR)", "Só dentro da janela do navegador"),
            ("sites", "Bloqueio de sites (lista)", "Arquivo hosts; vale em todo navegador · admin"),
            ("safesearch", "SafeSearch forçado", "Google, Bing e DuckDuckGo · admin"),
            ("autostart", "Iniciar com o Windows", "Liga sozinho quando você entra no PC"),
            ("forte", "Proteção forte", "Tarefa do Windows reabre em até 1 min se fechar · admin"),
        ]
        for i, (k, texto, dica) in enumerate(itens):
            c = ttk.Checkbutton(pf, text=texto, variable=self.v[k])
            c.grid(row=i, column=0, sticky="w", pady=1)
            ttk.Label(pf, text=dica, style="Info.TLabel").grid(row=i, column=1, sticky="w", padx=(12, 0))
            self.controles.append(c)

        # ajustes
        af = ttk.LabelFrame(r, text=" Ajustes ", padding=10)
        af.grid(sticky="ew", pady=(10, 0))
        ttk.Label(af, text="Cobrir:").grid(row=0, column=0, sticky="w")
        self.v_modo = tk.StringVar()
        for j, (val, txt) in enumerate((("parte", "só a área sensível"), ("tela", "a tela inteira"))):
            b = ttk.Radiobutton(af, text=txt, value=val, variable=self.v_modo)
            b.grid(row=0, column=1 + j, sticky="w", padx=(8, 0))
            self.controles.append(b)

        self.v_sens = tk.DoubleVar()
        self.v_margem = tk.DoubleVar()
        self.v_suave = tk.DoubleVar()
        self.lb_valores = {}
        escalas = [
            ("Sensibilidade", self.v_sens, 0, 100, "menos ← → mais"),
            ("Área extra", self.v_margem, 0, 100, "%"),
            ("Borda suave", self.v_suave, 0, 120, "px"),
        ]
        for i, (txt, var, a, b, uni) in enumerate(escalas, start=1):
            ttk.Label(af, text=txt + ":").grid(row=i, column=0, sticky="w", pady=3)
            e = ttk.Scale(af, from_=a, to=b, variable=var, length=230,
                          command=lambda _=None: self._mostrar_valores())
            e.grid(row=i, column=1, columnspan=2, sticky="w", padx=(8, 0))
            lb = ttk.Label(af, style="Info.TLabel", width=16)
            lb.grid(row=i, column=3, sticky="w", padx=(8, 0))
            self.lb_valores[txt] = (lb, var, uni)
            self.controles.append(e)

        # botões
        bf = ttk.Frame(r, padding=(0, 12, 0, 0))
        bf.grid(sticky="ew")
        botoes = [
            ("Salvar e aplicar", self.salvar, True),
            ("Pausar…", self.pausar, True),
            ("Retomar agora", self.retomar, False),
            ("Senha…", self.senha, False),
        ]
        for j, (txt, cmd, trava) in enumerate(botoes):
            b = ttk.Button(bf, text=txt, command=cmd)
            b.grid(row=0, column=j, padx=3, sticky="ew")
            if trava:
                self.controles.append(b)
        botoes2 = [
            ("Editar lista de sites", self.editar_sites, True),
            ("Ver log", lambda: self._abrir(os.path.join(config.PASTA, "logs", "bloqueador.log")), False),
            ("Abrir pasta", lambda: self._abrir(config.PASTA), False),
            ("Desligar tudo", self.desligar_tudo, True),
        ]
        for j, (txt, cmd, trava) in enumerate(botoes2):
            b = ttk.Button(bf, text=txt, command=cmd)
            b.grid(row=1, column=j, padx=3, pady=(6, 0), sticky="ew")
            if trava:
                self.controles.append(b)
        self.lb_dica = ttk.Label(r, style="Info.TLabel",
                                 text="Atalho para pausar sem o painel: Ctrl + Alt + Shift + Q")
        self.lb_dica.grid(sticky="w", pady=(10, 0))

    # ---------------- valores ----------------
    def _carregar_valores(self):
        c = self.cfg
        self.v["imagens"].set("nudez" in c["detectores"])
        self.v["titulo"].set(c["titulo_ativo"])
        self.v["ocr"].set(c["ocr"]["ativo"])
        self.v["sites"].set(c["bloquear_sites"])
        self.v["safesearch"].set(c["forcar_safesearch"])
        self.v["autostart"].set(protecao.autostart_ativo())
        self.v["forte"].set(protecao.tarefa_existe())
        self.v_modo.set(c["modo"])
        # limiar 1.6 (pouco sensível) .. 0.6 (muito sensível)
        self.v_sens.set(round((1.6 - c["limiar_bloqueio"]) * 100))
        self.v_margem.set(c["margem"] * 100)
        self.v_suave.set(c["suavizar_px"])
        self._mostrar_valores()

    def _mostrar_valores(self):
        for txt, (lb, var, uni) in self.lb_valores.items():
            v = var.get()
            if txt == "Sensibilidade":
                lb.config(text=f"{v:.0f}%  (limiar {1.6 - v / 100:.2f})")
            else:
                lb.config(text=f"{v:.0f} {uni}")

    # ---------------- senha / trava ----------------
    def _aplicar_trava(self):
        estado = "normal" if self.desbloqueado else "disabled"
        for c in self.controles:
            c.state(["!disabled"] if estado == "normal" else ["disabled"])
        if not protecao.tem_senha():
            self.bt_trava.config(text="Criar senha", command=self.senha)
        elif self.desbloqueado:
            self.bt_trava.config(text="🔓 Travar", command=self._alternar_trava)
        else:
            self.bt_trava.config(text="🔒 Desbloquear", command=self._alternar_trava)

    def _alternar_trava(self):
        if self.desbloqueado:
            self.desbloqueado = False
        else:
            s = pedir_senha(self.root)
            if s is None:
                return
            if not protecao.verificar_senha(s):
                messagebox.showerror("Senha", "Senha errada.", parent=self.root)
                return
            self.desbloqueado = True
        self._aplicar_trava()

    def _liberado(self):
        if self.desbloqueado:
            return True
        self._alternar_trava()
        return self.desbloqueado

    def senha(self):
        if protecao.tem_senha():
            atual = pedir_senha(self.root, "Trocar senha", "Senha atual:")
            if atual is None:
                return
            if not protecao.verificar_senha(atual):
                messagebox.showerror("Senha", "Senha atual errada.", parent=self.root)
                return
        nova = pedir_senha(self.root, "Nova senha", "Nova senha (mín. 4 caracteres):")
        if not nova:
            return
        if len(nova) < 4:
            messagebox.showerror("Senha", "Use pelo menos 4 caracteres.", parent=self.root)
            return
        if nova != pedir_senha(self.root, "Nova senha", "Repita a nova senha:"):
            messagebox.showerror("Senha", "As senhas não batem.", parent=self.root)
            return
        protecao.definir_senha(nova)
        self.desbloqueado = True
        self._aplicar_trava()
        messagebox.showinfo("Senha", "Senha salva. Ela será pedida para pausar,\n"
                            "mudar ajustes ou desligar a proteção.", parent=self.root)

    # ---------------- ações ----------------
    def salvar(self):
        if not self._liberado():
            return
        cfg = config.carregar()
        cfg["detectores"] = ["nudez"] if self.v["imagens"].get() else []
        cfg["titulo_ativo"] = self.v["titulo"].get()
        cfg["ocr"]["ativo"] = self.v["ocr"].get()
        cfg["bloquear_sites"] = self.v["sites"].get()
        cfg["forcar_safesearch"] = self.v["safesearch"].get()
        cfg["modo"] = self.v_modo.get()
        cfg["limiar_bloqueio"] = round(1.6 - self.v_sens.get() / 100, 2)
        cfg["margem"] = round(self.v_margem.get() / 100, 2)
        cfg["suavizar_px"] = int(self.v_suave.get())
        config.salvar(cfg)  # o bloqueador percebe e reinicia sozinho
        self.cfg = cfg

        avisos = []
        if self.v["autostart"].get() != protecao.autostart_ativo():
            protecao.autostart(self.v["autostart"].get())

        acoes = []
        lista = config.caminho(cfg["sites_bloqueados"])
        try:
            desejada = sites.secao_desejada(lista, cfg["bloquear_sites"], cfg["forcar_safesearch"])
            if desejada != sites.secao_atual():
                acoes.append("hosts_aplicar")
        except Exception as e:
            avisos.append(f"Não consegui ler a lista de sites: {e}")
        if self.v["forte"].get() != protecao.tarefa_existe():
            acoes.append("tarefa_criar" if self.v["forte"].get() else "tarefa_remover")
        if acoes:
            self.root.config(cursor="watch")
            self.root.update()
            ok = protecao.rodar_admin(*acoes)
            self.root.config(cursor="")
            if not ok:
                avisos.append("As opções de administrador (sites, SafeSearch, proteção forte)\n"
                              "não foram aplicadas: o aviso do Windows foi recusado.")
                self._carregar_valores_admin()

        if not protecao.pausa_ativa() and not protecao.esta_rodando("app"):
            protecao.iniciar_app()
        if self.v["autostart"].get() and not protecao.esta_rodando("guardiao"):
            protecao.iniciar_guardiao()
        if avisos:
            messagebox.showwarning("Bloqueador", "\n\n".join(avisos), parent=self.root)
        else:
            messagebox.showinfo("Bloqueador", "Salvo e aplicado.", parent=self.root)

    def _carregar_valores_admin(self):
        self.v["forte"].set(protecao.tarefa_existe())

    def pausar(self):
        if not self._liberado():
            return
        m = simpledialog.askinteger("Pausar", "Pausar por quantos minutos?", parent=self.root,
                                    initialvalue=30, minvalue=1, maxvalue=1440)
        if not m:
            return
        protecao.pausar(m)
        protecao.parar_app()

    def retomar(self):
        protecao.cancelar_pausa()
        if not protecao.esta_rodando("app"):
            protecao.iniciar_app()

    def editar_sites(self):
        if self._liberado():
            self._abrir(config.caminho(self.cfg["sites_bloqueados"]))
            messagebox.showinfo("Sites", "Edite, salve o arquivo e depois clique em\n"
                                "\"Salvar e aplicar\" aqui no painel.", parent=self.root)

    def desligar_tudo(self):
        if not self._liberado():
            return
        if not messagebox.askyesno("Desligar tudo", "Desligar o bloqueador, o início com o Windows,\n"
                                   "a proteção forte e o bloqueio de sites?", parent=self.root):
            return
        protecao.pausar(60 * 24 * 365)
        protecao.autostart(False)
        acoes = []
        if sites.secao_atual():
            acoes.append("hosts_remover")
        if protecao.tarefa_existe():
            acoes.append("tarefa_remover")
        if acoes:
            protecao.rodar_admin(*acoes)
        for p in protecao.processos():
            try:
                p.kill()
            except Exception:
                pass
        self._carregar_valores()
        messagebox.showinfo("Bloqueador", "Tudo desligado. Para voltar: \"Retomar agora\"\n"
                            "e marque \"Iniciar com o Windows\".", parent=self.root)

    @staticmethod
    def _abrir(caminho):
        if os.path.exists(caminho):
            os.startfile(caminho)

    # ---------------- status ----------------
    def _status(self):
        try:
            with open(os.path.join(config.DADOS, "status.json"), encoding="utf-8") as f:
                st = json.load(f)
        except Exception:
            st = {}
        rodando = protecao.esta_rodando("app") and \
            time.time() - st.get("atualizado", 0) < 8 and psutil.pid_exists(st.get("pid", -1))
        if rodando:
            cor, txt = COR_ATIVO, "ATIVO" + ("  ·  bloqueando agora" if st.get("bloqueando") else "")
            disp = st.get("dispositivo", "?").replace("DmlExecutionProvider", "GPU (DirectML)")                 .replace("CUDAExecutionProvider", "GPU (CUDA)").replace("CPUExecutionProvider", "CPU")
            info = (f"{disp}  ·  {st.get('analises_s', 0)} análises/s  ·  "
                    f"{st.get('ms', 0)} ms por análise")
        elif protecao.pausa_ativa():
            cor = COR_PAUSA
            txt = "PAUSADO até " + time.strftime("%H:%M", time.localtime(protecao.pausa_ate()))
            info = "Clique em \"Retomar agora\" para voltar antes."
        elif protecao.esta_rodando("app"):
            cor, txt, info = COR_PAUSA, "INICIANDO…", "Carregando os modelos de IA."
        else:
            cor, txt, info = COR_OFF, "DESLIGADO", "Clique em \"Retomar agora\" para ligar."
        self.lb_bola.config(fg=cor)
        self.lb_status.config(text=txt, foreground=cor)
        self.lb_info.config(text=info)
        ult = st.get("ultimo_bloqueio")
        self.lb_ultimo.config(text=f"Último bloqueio: {ult}" if ult else "")
        self.root.after(1000, self._status)


if __name__ == "__main__":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    os.chdir(config.PASTA)
    if protecao.instancia_unica("painel"):
        Painel().root.mainloop()
