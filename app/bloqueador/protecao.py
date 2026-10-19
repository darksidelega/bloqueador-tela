"""Autoproteção: modo restrito, pausa, instância única, início automático.

Modo restrito (como o "Strict mode" do AppBlock): até o horário escolhido
não dá para pausar, desligar proteções nem desinstalar pelo painel; só dá
para deixar mais rígido. Fica gravado em dados/restrito.json e no registro,
assinado com uma chave local (editar à mão invalida).
"""
import ctypes
import hmac
import json
import os
import secrets
import subprocess
import sys
import time

from . import config

ARQ_CHAVE = os.path.join(config.DADOS, "chave.bin")
ARQ_PAUSA = os.path.join(config.DADOS, "pausa.json")
ARQ_RESTRITO = os.path.join(config.DADOS, "restrito.json")
ARQ_DESBLOQUEIO = os.path.join(config.DADOS, "desbloqueio.json")
# Modo restrito "sem prazo": guardado com este horário-fim lá no futuro
# (~ano 3000). Só sai pedindo o desbloqueio e esperando (ver pedir_desbloqueio).
INDEFINIDO = 32503680000
NOME_TAREFA = "BloqueadorTela"
CHAVE_APP = r"Software\BloqueadorTela"
kernel32 = ctypes.windll.kernel32


# ---------------- assinatura ----------------
def _chave():
    if not os.path.isfile(ARQ_CHAVE):
        with open(ARQ_CHAVE, "wb") as f:
            f.write(secrets.token_bytes(32))
    with open(ARQ_CHAVE, "rb") as f:
        return f.read()


def _assinatura(tipo, ate):
    return hmac.new(_chave(), f"{tipo}:{ate}".encode(), "sha256").hexdigest()


def _gravar(arq, tipo, ate):
    with open(arq, "w", encoding="utf-8") as f:
        json.dump({"ate": ate, "assinatura": _assinatura(tipo, ate)}, f)


def _ler(arq, tipo):
    """Horário (epoch) gravado e válido, ou 0."""
    try:
        with open(arq, encoding="utf-8") as f:
            d = json.load(f)
        if hmac.compare_digest(d["assinatura"], _assinatura(tipo, d["ate"])):
            return d["ate"]
    except Exception:
        pass
    return 0


# ---------------- modo restrito ----------------
def _registro(valor=None):
    import winreg
    try:
        if valor is None:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_APP) as k:
                return json.loads(winreg.QueryValueEx(k, "Restrito")[0])
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, CHAVE_APP) as k:
            winreg.SetValueEx(k, "Restrito", 0, winreg.REG_SZ, json.dumps(valor))
    except OSError:
        return None


def _restrito_gravado():
    """(do arquivo, do registro): horários válidos gravados (0 = nada/inválido)."""
    reg, do_reg = _registro(), 0
    if reg:
        try:
            if hmac.compare_digest(reg["assinatura"], _assinatura("restrito", reg["ate"])):
                do_reg = reg["ate"]
        except Exception:
            pass
    return _ler(ARQ_RESTRITO, "restrito"), do_reg


# o app e o guardião lembram o horário: apagar o arquivo e a chave do registro
# não desliga o restrito enquanto um dos dois estiver rodando
_restrito_memoria = 0


def _restrito_bruto():
    """Horário-fim gravado (arquivo/registro/memória), sem olhar o relógio nem
    o pedido de desbloqueio. INDEFINIDO = modo sem prazo."""
    return max(_restrito_memoria, *_restrito_gravado())


def restrito_ate():
    """Até quando o modo restrito vale (epoch), ou 0 se desligado. No modo sem
    prazo devolve o fim do pedido de desbloqueio, ou INDEFINIDO se não há."""
    bruto = _restrito_bruto()
    if bruto <= time.time():
        return 0
    if bruto >= INDEFINIDO:  # sem prazo: só acaba quando a espera é cumprida
        d = _ler(ARQ_DESBLOQUEIO, "desbloqueio")
        if d and d <= time.time():
            return 0
    return bruto


def restrito_ativo():
    return restrito_ate() > 0


def restrito_indefinido():
    """True se o modo restrito está ligado e é do tipo "sem prazo"."""
    return restrito_ativo() and _restrito_bruto() >= INDEFINIDO


def desbloqueio_em():
    """Epoch em que o modo restrito sem prazo vai se desligar (pedido de
    desbloqueio em andamento), ou 0 se não há pedido."""
    if _restrito_bruto() < INDEFINIDO:
        return 0
    d = _ler(ARQ_DESBLOQUEIO, "desbloqueio")
    return d if d > time.time() else 0


def _gravar_restrito(ate):
    _gravar(ARQ_RESTRITO, "restrito", ate)
    _registro({"ate": ate, "assinatura": _assinatura("restrito", ate)})


def _apagar_restrito():
    """Desliga o modo restrito de vez: apaga os registros e o pedido de
    desbloqueio."""
    for arq in (ARQ_RESTRITO, ARQ_DESBLOQUEIO):
        try:
            os.remove(arq)
        except OSError:
            pass
    _registro({"ate": 0, "assinatura": _assinatura("restrito", 0)})


def ativar_restrito(minutos):
    """Liga (ou estende) o modo restrito com prazo. Nunca encurta."""
    novo = not restrito_ativo()
    ate = int(max(restrito_ate(), time.time() + minutos * 60))
    if ate >= INDEFINIDO:  # já estava sem prazo: continua sem prazo
        ate = INDEFINIDO
    if novo or _ler_cfg_restrito() is None:
        _guardar_cfg_restrito(config.carregar())
    _gravar_restrito(ate)
    cancelar_pausa()
    return ate


def ativar_restrito_livre(espera_min=None):
    """Liga o modo restrito "sem prazo" (como o Strict do ScreenZen): não tem
    hora para acabar; só sai com pedir_desbloqueio() + espera. Nunca encurta.
    `espera_min` (quando o modo ainda não estava ligado) define quanto o
    desbloqueio vai demorar — o usuário escolhe: 30, mais, ou menos."""
    novo = not restrito_ativo()
    if espera_min is not None and novo:
        cfg = config.carregar()
        cfg["espera_desbloqueio_min"] = max(1, int(espera_min))
        config.salvar(cfg)
    if novo or _ler_cfg_restrito() is None:
        _guardar_cfg_restrito(config.carregar())
    cancelar_desbloqueio()  # começar sem prazo cancela qualquer pedido pendente
    _gravar_restrito(INDEFINIDO)
    cancelar_pausa()
    return INDEFINIDO


def pedir_desbloqueio():
    """Começa a espera para sair do modo restrito sem prazo. Devolve o epoch em
    que vai desligar, ou 0 se não se aplica. Não reinicia um pedido em andamento
    (não dá para "renovar" para ganhar tempo) nem o encurta."""
    if not restrito_indefinido():
        return 0
    atual = _ler(ARQ_DESBLOQUEIO, "desbloqueio")
    if atual and atual > time.time():
        return atual
    espera = config_efetivo().get("espera_desbloqueio_min", 30)
    d = int(time.time() + max(1, espera) * 60)
    _gravar(ARQ_DESBLOQUEIO, "desbloqueio", d)
    return d


def cancelar_desbloqueio():
    """Desiste do desbloqueio: o modo restrito sem prazo volta a travar."""
    try:
        os.remove(ARQ_DESBLOQUEIO)
    except OSError:
        pass


_relogio = None  # (hora do relógio, tempo desde que o PC ligou) da última volta


def _ms_ligado():
    """Milissegundos desde que o PC ligou, contando o tempo dormindo (não
    muda se alguém mexer no relógio)."""
    kernel32.GetTickCount64.restype = ctypes.c_uint64
    return kernel32.GetTickCount64()


def vigiar_restrito():
    """Chamado a cada ~2 s pelo app e pelo guardião. Mantém o modo restrito
    de pé contra quem apaga os arquivos ou adianta o relógio. Retorna se
    está ativo."""
    global _restrito_memoria, _relogio
    do_arq, do_reg = _restrito_gravado()
    ate = max(_restrito_memoria, do_arq, do_reg)
    agora, ligado = time.time(), _ms_ligado() / 1000
    sem_prazo = ate >= INDEFINIDO
    d = _ler(ARQ_DESBLOQUEIO, "desbloqueio") if sem_prazo else 0
    if _relogio and ate:
        # o relógio andou bem mais que o tempo de verdade: adiantaram a hora.
        # Estende o prazo (ou empurra a espera de desbloqueio) na mesma medida,
        # senão dava para pular o tempo só mudando o relógio.
        pulo = (agora - _relogio[0]) - (ligado - _relogio[1])
        if pulo > 120:
            if not sem_prazo:
                ate += int(pulo)
            if d:
                d += int(pulo)
                try:
                    _gravar(ARQ_DESBLOQUEIO, "desbloqueio", d)
                except OSError:
                    pass
            print(f"Relógio adiantado {pulo / 3600:.1f} h: o modo restrito foi estendido igual.")
    _relogio = (agora, ligado)
    # desliga: prazo acabou, ou a espera de desbloqueio foi cumprida
    if ate <= agora or (sem_prazo and d and d <= agora):
        _restrito_memoria = 0
        _apagar_restrito()
        vigia(False)
        return False
    _restrito_memoria = ate
    vigia(True)
    alvo = INDEFINIDO if sem_prazo else ate
    if do_arq != alvo or do_reg != alvo:
        try:
            _gravar_restrito(alvo)  # alguém apagou ou mexeu: regrava
        except OSError:
            pass
    garantir_autostart()
    return True


# ---------------- config travado no modo restrito ----------------
# Ao ligar o restrito, guarda uma cópia assinada do config. Até acabar, o app
# parte dela e só aceita do config.json o que deixa mais rígido: editar o
# arquivo à mão (zerar pesos, intervalo enorme, tirar o Chrome da lista...)
# não muda nada, nem reiniciando o app.
ARQ_CFG_RESTRITO = os.path.join(config.DADOS, "config_restrito.json")


def _assinatura_cfg(cfg):
    texto = json.dumps(cfg, sort_keys=True, ensure_ascii=False)
    return hmac.new(_chave(), b"config:" + texto.encode(), "sha256").hexdigest()


def _guardar_cfg_restrito(cfg):
    try:
        with open(ARQ_CFG_RESTRITO, "w", encoding="utf-8") as f:
            json.dump({"cfg": cfg, "assinatura": _assinatura_cfg(cfg)}, f, ensure_ascii=False)
    except OSError:
        pass  # sem a cópia, vale o padrão (que tem tudo ligado)


def _ler_cfg_restrito():
    try:
        with open(ARQ_CFG_RESTRITO, encoding="utf-8") as f:
            d = json.load(f)
        if hmac.compare_digest(d["assinatura"], _assinatura_cfg(d["cfg"])):
            return d["cfg"]
    except Exception:
        pass
    return None


def mais_rigido(base, novo):
    """`base` com só as mudanças de `novo` que protegem mais (ou que não
    são proteção, como o lembrete de pausa)."""
    import copy
    cfg = copy.deepcopy(base)
    cfg["detectores"] = sorted(set(base["detectores"]) | set(novo["detectores"]))
    for chave in ("titulo_ativo", "esconder_previas", "bloquear_shorts",
                  "bloquear_sites", "forcar_safesearch"):
        cfg[chave] = base[chave] or novo[chave]
    cfg["ocr"]["ativo"] = base["ocr"]["ativo"] or novo["ocr"]["ativo"]
    for chave in ("limiar_bloqueio", "limiar_com_palavra", "travar_pagina_fotos",
                  "limiar_grande", "regiao_grande_cobrir"):
        cfg[chave] = min(base[chave], novo[chave])
    cfg["margem"] = max(base["margem"], novo["margem"])
    # espera de desbloqueio só pode aumentar (esperar mais é mais rígido)
    cfg["espera_desbloqueio_min"] = max(base["espera_desbloqueio_min"],
                                        novo["espera_desbloqueio_min"])
    # exceções: não dá para ADICIONAR janela ignorada no modo restrito (seria
    # afrouxar); só mantém as que já existiam (tirar exceção é mais rígido).
    cfg["excecoes"] = [e for e in novo["excecoes"] if e in base["excecoes"]]
    # modo horário: não dá para desligar o agendamento no modo restrito
    h = dict(novo["horario_restrito"])
    h["ativo"] = base["horario_restrito"]["ativo"] or novo["horario_restrito"]["ativo"]
    cfg["horario_restrito"] = h
    if "tela" in (base["modo"], novo["modo"]):
        cfg["modo"] = "tela"
    for chaves in config.LISTAS + (("navegadores",),):
        pai, de_novo = cfg, novo
        for k in chaves[:-1]:
            pai, de_novo = pai[k], de_novo[k]
        k = chaves[-1]
        pai[k] = pai[k] + [p for p in de_novo[k] if p not in pai[k]]
    for chave in ("lembrete_pausa", "bloqueio_rapido_min", "suavizar_px", "debug", "dias_log"):
        cfg[chave] = novo[chave]
    return cfg


def config_efetivo():
    """O config que o app usa: o do arquivo, ou, no modo restrito, a cópia
    guardada (ou o padrão, se mexeram nela) com só o que deixa mais rígido."""
    arq = config.carregar()
    if not restrito_ativo():
        return arq
    base = _ler_cfg_restrito()
    if base is None:
        import copy
        base = copy.deepcopy(config.PADRAO)
    else:
        base = config.completar(base)
    try:
        return mais_rigido(base, arq)
    except Exception:  # valor de tipo errado no arquivo: ignora o arquivo
        return base


# ---------------- iniciar com o Windows forçado no modo restrito ----------------
CHAVE_APROVADOS = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def garantir_autostart():
    """Desabilitar em Gerenciador de Tarefas > Aplicativos de inicialização
    (ou apagar do registro) não vale no modo restrito: volta sozinho."""
    import winreg
    try:
        if not autostart_ativo():
            autostart(True)
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_APROVADOS, 0,
                            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE) as k:
            estado = winreg.QueryValueEx(k, NOME_TAREFA)[0]
            if estado and estado[0] & 1:  # 0x03 = desabilitado
                winreg.DeleteValue(k, NOME_TAREFA)
    except OSError:
        pass


def bloqueio_rapido():
    """Um clique, sem perguntas: liga o modo restrito e todas as proteções
    que não pedem admin. Retorna até quando vale."""
    cfg = config.carregar()
    ate = ativar_restrito(cfg["bloqueio_rapido_min"])
    novo = config.carregar()
    if "nudez" not in novo["detectores"]:
        novo["detectores"].append("nudez")
    novo["titulo_ativo"] = novo["ocr"]["ativo"] = True
    if novo != cfg:
        config.salvar(novo)
    return ate


# ---------------- modo horário (Modo restrito automático) ----------------
def _minutos_do_dia(hhmm):
    h, m = str(hhmm).split(":")
    return int(h) * 60 + int(m)


def horario_restrito_agora(cfg, agora=None):
    """Minutos que faltam até o fim da janela de horário, se o modo horário
    está ligado e agora cai dentro dela; senão 0. Só usa o relógio (offline)."""
    h = cfg.get("horario_restrito") or {}
    if not h.get("ativo"):
        return 0
    try:
        ini, fim = _minutos_do_dia(h["inicio"]), _minutos_do_dia(h["fim"])
    except (ValueError, KeyError, AttributeError, TypeError):
        return 0
    if ini == fim:
        return 0
    t = time.localtime(agora if agora is not None else time.time())
    agora_min = t.tm_hour * 60 + t.tm_min
    dentro = ini <= agora_min < fim if ini < fim else (agora_min >= ini or agora_min < fim)
    if not dentro:
        return 0
    return max(1, (fim - agora_min) % (24 * 60))  # atravessa a meia-noite se preciso


def aplicar_horario(cfg=None):
    """Liga o Modo restrito sozinho dentro da janela de horário configurada.
    Idempotente e nunca encurta; não mexe no modo restrito sem prazo. Retorna
    True se a janela está valendo agora."""
    cfg = cfg or config_efetivo()
    falta = horario_restrito_agora(cfg)
    if falta and not restrito_indefinido():
        ativar_restrito(falta)
    return bool(falta)


# ---------------- prévias das janelas (barra de tarefas e Alt+Tab) ----------------
CHAVE_AVANCADO = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
CHAVE_EXPLORER = r"Software\Microsoft\Windows\CurrentVersion\Explorer"
CHAVE_DWM = r"Software\Microsoft\Windows\DWM"
# (chave, valor, quando esconder): prévia da barra só depois de 1 min parado
# em cima (na prática nunca), Alt+Tab clássico, só com ícones, e sem o
# "Espiar" (Aero Peek): passar o mouse no nome da janela na lista da barra
# mostrava a janela inteira e deixava todo o resto, inclusive o mosaico,
# transparente
PREVIAS = ((CHAVE_AVANCADO, "ExtendedUIHoverTime", 60000),
           (CHAVE_EXPLORER, "AltTabSettings", 1),
           (CHAVE_DWM, "EnableAeroPeek", 0))


def previas_escondidas():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_EXPLORER) as k:
            return winreg.QueryValueEx(k, "AltTabSettings")[0] == 1
    except OSError:
        return False


def esconder_previas(esconder):
    """Liga/desliga as miniaturas e reinicia o Explorer (a barra pisca)."""
    import winreg
    for chave, nome, valor in PREVIAS:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, chave) as k:
            if esconder:
                winreg.SetValueEx(k, nome, 0, winreg.REG_DWORD, valor)
            else:
                try:
                    winreg.DeleteValue(k, nome)
                except OSError:
                    pass
    subprocess.run(["taskkill", "/f", "/im", "explorer.exe"], capture_output=True,
                   creationflags=SEM_JANELA)
    time.sleep(1)
    subprocess.Popen(["explorer.exe"], creationflags=0x00000008)  # separado


# ---------------- trava dos arquivos ----------------
_travados = []


def _arquivos_protegidos():
    """Código do app, modelos e a chave que assina o modo restrito
    (apagar a chave anularia o modo restrito)."""
    pastas = [config.APP, os.path.join(config.PASTA, "modelos"), PASTA_EXTENSAO]
    for pasta in pastas:
        for raiz, _, nomes in os.walk(pasta):
            if "__pycache__" in raiz:
                continue
            for n in nomes:  # trava TODO arquivo: não dá para apagar nem um solto
                yield os.path.join(raiz, n), False
    yield ARQ_CHAVE, False
    yield ARQ_RESTRITO, True  # o Painel precisa poder regravar (estender)
    yield ARQ_DESBLOQUEIO, True  # o Painel pede/cancela o desbloqueio
    yield ARQ_CFG_RESTRITO, True
    # o Python e as bibliotecas que este processo usa: apagar uma delas
    # impediria o app de abrir de novo
    yield os.path.join(config.PASTA, ".venv", "pyvenv.cfg"), False
    for m in list(sys.modules.values()):
        arq = getattr(m, "__file__", None)
        if arq and arq.endswith((".py", ".pyd")):
            yield arq, False


def travar_arquivos(ligar):
    """Segura os arquivos do app abertos sem permitir apagar/renomear: o
    Windows responde "arquivo em uso" para quem tentar apagar a pasta."""
    if not ligar:
        while _travados:
            kernel32.CloseHandle(ctypes.c_void_p(_travados.pop()))
        return
    if _travados:
        return
    kernel32.CreateFileW.restype = ctypes.c_void_p
    GENERIC_READ, FILE_SHARE_READ, FILE_SHARE_WRITE, OPEN_EXISTING = 0x80000000, 1, 2, 3
    for caminho, gravavel in _arquivos_protegidos():
        partilha = FILE_SHARE_READ | (FILE_SHARE_WRITE if gravavel else 0)
        h = kernel32.CreateFileW(caminho, GENERIC_READ, partilha, None, OPEN_EXISTING, 0, None)
        if h and h != ctypes.c_void_p(-1).value:
            _travados.append(h)


# ---------------- não deixar encerrar o processo ----------------
class _Trustee(ctypes.Structure):
    _fields_ = [("pMultipleTrustee", ctypes.c_void_p), ("MultipleTrusteeOperation", ctypes.c_int),
                ("TrusteeForm", ctypes.c_int), ("TrusteeType", ctypes.c_int),
                ("ptstrName", ctypes.c_wchar_p)]


class _AcessoExplicito(ctypes.Structure):
    _fields_ = [("grfAccessPermissions", ctypes.c_uint32), ("grfAccessMode", ctypes.c_int),
                ("grfInheritance", ctypes.c_uint32), ("Trustee", _Trustee)]


_dacl_original = []  # [ponteiro da DACL, descritor] de quando o processo abriu


def proteger_processo(ligar):
    """No modo restrito, nega "encerrar" ao seu próprio usuário: o
    Gerenciador de Tarefas e o taskkill recebem "Acesso negado". Um
    administrador com privilégio de depuração ainda consegue (aí só a
    Proteção forte segura)."""
    adv = ctypes.WinDLL("advapi32")
    k32 = ctypes.WinDLL("kernel32")
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    adv.SetSecurityInfo.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
    adv.GetSecurityInfo.argtypes = (ctypes.c_void_p, ctypes.c_int, ctypes.c_uint32, ctypes.c_void_p,
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
                                    ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    adv.SetEntriesInAclW.argtypes = (ctypes.c_uint32, ctypes.POINTER(_AcessoExplicito),
                                     ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))
    SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION = 6, 4
    eu = k32.GetCurrentProcess()
    if not _dacl_original:
        dacl, sd = ctypes.c_void_p(), ctypes.c_void_p()
        if adv.GetSecurityInfo(eu, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION, None, None,
                               ctypes.byref(dacl), None, ctypes.byref(sd)):
            return False
        _dacl_original.extend([dacl, sd])  # sd fica vivo: a DACL aponta para dentro dele
    if not ligar:
        return adv.SetSecurityInfo(eu, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION,
                                   None, None, _dacl_original[0], None) == 0
    PROCESS_TERMINATE, DENY_ACCESS, TRUSTEE_IS_NAME, TRUSTEE_IS_USER = 0x0001, 3, 1, 1
    negar = _AcessoExplicito(PROCESS_TERMINATE, DENY_ACCESS, 0,
                             _Trustee(None, 0, TRUSTEE_IS_NAME, TRUSTEE_IS_USER, "CURRENT_USER"))
    nova = ctypes.c_void_p()
    if adv.SetEntriesInAclW(1, ctypes.byref(negar), _dacl_original[0], ctypes.byref(nova)):
        return False
    ok = adv.SetSecurityInfo(eu, SE_KERNEL_OBJECT, DACL_SECURITY_INFORMATION,
                             None, None, nova, None) == 0
    k32.LocalFree.argtypes = (ctypes.c_void_p,)
    k32.LocalFree(nova)
    return ok


# ---------------- pausa ----------------
def pausar(minutos):
    """Pausa o bloqueador (o guardião não o reabre). Bloqueado no modo restrito."""
    if restrito_ativo():
        return False
    _gravar(ARQ_PAUSA, "pausa", int(time.time() + minutos * 60))
    return True


def pausa_ate():
    ate = _ler(ARQ_PAUSA, "pausa")
    return ate if ate > time.time() and not restrito_ativo() else 0


def pausa_ativa():
    return pausa_ate() > 0


def cancelar_pausa():
    try:
        os.remove(ARQ_PAUSA)
    except OSError:
        pass


# ---------------- instância única ----------------
_mutexes = []


def instancia_unica(nome):
    """True se esta é a única instância com esse nome."""
    h = kernel32.CreateMutexW(None, False, f"Local\\bloqueador_tela_{nome}")
    _mutexes.append(h)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def esta_rodando(nome):
    SYNCHRONIZE = 0x00100000
    h = kernel32.OpenMutexW(SYNCHRONIZE, False, f"Local\\bloqueador_tela_{nome}")
    if h:
        kernel32.CloseHandle(h)
        return True
    return False


# ---------------- iniciar/parar ----------------
SEM_JANELA = 0x08000000


def pythonw():
    """pythonw.exe do .venv do projeto (sem janela de console)."""
    venv = os.path.join(config.PASTA, ".venv", "Scripts", "pythonw.exe")
    if os.path.isfile(venv):
        return venv
    w = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return w if os.path.isfile(w) else sys.executable


def script(nome):
    return os.path.join(config.APP, nome)


def comando_guardiao():
    """(programa, argumentos) para iniciar o guardião."""
    return pythonw(), f'"{script("guardiao.py")}"'


def _python_direto():
    """(programa, ambiente) do Python de verdade, sem o lançador do .venv.
    O pythonw.exe do .venv só abre o Python real como filho, preso no mesmo
    grupo (job): finalizar o lançador, que não tem proteção, derrubava o app
    protegido junto. A variável faz o Python real usar as bibliotecas do .venv,
    igual o lançador faria."""
    venv = os.path.join(config.PASTA, ".venv")
    try:
        with open(os.path.join(venv, "pyvenv.cfg"), encoding="utf-8") as f:
            home = next(linha.split("=", 1)[1].strip() for linha in f
                        if linha.split("=", 1)[0].strip() == "home")
        real = os.path.join(home, "pythonw.exe")
        if os.path.isfile(real):
            return real, dict(os.environ,
                              __PYVENV_LAUNCHER__=os.path.join(venv, "Scripts", "pythonw.exe"))
    except (OSError, StopIteration):
        pass
    return pythonw(), None


def _iniciar(nome):
    prog, ambiente = _python_direto()
    flags = SEM_JANELA | 0x00000008  # sem janela, separado
    try:  # sai do grupo (job) de quem abriu, se houver
        subprocess.Popen([prog, script(nome)], cwd=config.PASTA, env=ambiente,
                         creationflags=flags | 0x01000000)  # CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        subprocess.Popen([prog, script(nome)], cwd=config.PASTA, env=ambiente,
                         creationflags=flags)


def iniciar_guardiao():
    _iniciar("guardiao.py")


def iniciar_app():
    _iniciar("bloqueador_tela.py")


# ---------------- extensão de vídeos curtos (native messaging) ----------------
# A extensão (pasta extensao/) esconde Shorts/Reels/feed do TikTok. Ela pergunta
# a este "host" se deve esconder; o Chrome encontra o host por estas chaves de
# registro. O ID da extensão vem da chave pública embutida no manifest.json.
EXT_ID = "jadhohegbffojblpppanbfcokdjeokkc"
HOST_CURTOS = "com.bloqueadortela.curtos"
ARQ_HOST_JSON = os.path.join(config.DADOS, "host_curtos.json")
ARQ_HOST_BAT = os.path.join(config.DADOS, "host_curtos.bat")
PASTA_EXTENSAO = os.path.join(config.PASTA, "extensao")
# cada navegador procura o host numa chave própria (todos em HKCU, sem admin)
CHAVES_HOST = (r"Software\Google\Chrome\NativeMessagingHosts",
               r"Software\Microsoft\Edge\NativeMessagingHosts",
               r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts")


def _pythonw_base():
    """pythonw.exe do Python de verdade (o host só usa a biblioteca padrão)."""
    prog, _ = _python_direto()
    return prog


def registrar_host_curtos():
    """Cria o .bat, o manifesto e as chaves de registro para o Chrome/Edge/Brave
    acharem o host. Sem admin."""
    import winreg
    with open(ARQ_HOST_BAT, "w", encoding="utf-8") as f:
        f.write(f'@echo off\r\n"{_pythonw_base()}" "{script("host_curtos.py")}"\r\n')
    manifesto = {
        "name": HOST_CURTOS,
        "description": "Bloqueador de Tela - ajuste de videos curtos",
        "path": ARQ_HOST_BAT,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{EXT_ID}/"],
    }
    with open(ARQ_HOST_JSON, "w", encoding="utf-8") as f:
        json.dump(manifesto, f)
    for base in CHAVES_HOST:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, base + "\\" + HOST_CURTOS) as k:
            winreg.SetValueEx(k, None, 0, winreg.REG_SZ, ARQ_HOST_JSON)


def remover_host_curtos():
    import winreg
    for base in CHAVES_HOST:
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, base + "\\" + HOST_CURTOS)
        except OSError:
            pass


def host_curtos_registrado():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVES_HOST[0] + "\\" + HOST_CURTOS) as k:
            return winreg.QueryValueEx(k, None)[0] == ARQ_HOST_JSON
    except OSError:
        return False


def aberto_pelo_lancador():
    """Este processo foi aberto pelo lançador do .venv (início com o Windows,
    tarefa agendada)? Aí ele deve se reabrir direto e sair."""
    import psutil
    try:
        pai = psutil.Process().parent()
        return pai is not None and os.path.normcase(os.path.dirname(pai.exe())) == \
            os.path.normcase(os.path.join(config.PASTA, ".venv", "Scripts"))
    except Exception:
        return False


# ---------------- tarefa vigia (sem admin) no modo restrito ----------------
NOME_VIGIA = "BloqueadorTelaVigia"
_vigia = {"existe": None, "conferida": 0.0}


def vigia(ligar):
    """No modo restrito, uma tarefa agendada do seu usuário (não pede admin)
    reabre o guardião a cada minuto: mesmo que alguém consiga finalizar o
    app e o guardião juntos, eles voltam. Sai quando o restrito acaba."""
    agora = time.time()
    if _vigia["existe"] is False and not ligar:
        return  # já sabe que não existe: não consulta à toa
    if _vigia["existe"] == ligar and agora - _vigia["conferida"] < 60:
        return
    _vigia["conferida"] = agora
    existe = subprocess.run(["schtasks", "/Query", "/TN", NOME_VIGIA], capture_output=True,
                            creationflags=SEM_JANELA).returncode == 0
    if ligar and not existe:
        prog, args = comando_guardiao()
        r = subprocess.run(["schtasks", "/Create", "/TN", NOME_VIGIA, "/SC", "MINUTE", "/MO", "1",
                            "/TR", f'"{prog}" {args}', "/F"], capture_output=True,
                           creationflags=SEM_JANELA)
        existe = r.returncode == 0
    elif not ligar and existe:
        subprocess.run(["schtasks", "/Delete", "/TN", NOME_VIGIA, "/F"], capture_output=True,
                       creationflags=SEM_JANELA)
        existe = False
    _vigia["existe"] = existe


def processos(nomes=("bloqueador_tela.py", "guardiao.py")):
    import psutil
    achados = []
    for p in psutil.process_iter(["name", "cmdline"]):
        cmd = p.info["cmdline"] or []
        eh_python = (p.info["name"] or "").lower().startswith("python")
        if eh_python and any(c.endswith(nomes) for c in cmd[1:]):
            achados.append(p)
    return achados


def parar_app():
    for p in processos(("bloqueador_tela.py",)):
        try:
            p.kill()
        except Exception:
            pass


def liberar_mutexes():
    while _mutexes:
        kernel32.CloseHandle(_mutexes.pop())


# ---------------- iniciar com o Windows (sem admin) ----------------
CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def autostart_ativo():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as k:
            winreg.QueryValueEx(k, NOME_TAREFA)
        return True
    except OSError:
        return False


def autostart(ligar):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            prog, args = comando_guardiao()
            winreg.SetValueEx(k, NOME_TAREFA, 0, winreg.REG_SZ, f'"{prog}" {args}')
        else:
            try:
                winreg.DeleteValue(k, NOME_TAREFA)
            except OSError:
                pass


# ---------------- ações que precisam de administrador ----------------
def rodar_admin(*args):
    """Roda app/admin.py elevado (aparece o aviso do Windows). Retorna True se deu certo."""
    lista = ",".join(f"'{a}'" for a in ('"' + script("admin.py") + '"',) + args)
    ps = (f"$p = Start-Process -FilePath '{pythonw()}' -ArgumentList {lista} "
          f"-Verb RunAs -Wait -PassThru -WindowStyle Hidden; exit $p.ExitCode")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, creationflags=SEM_JANELA)
    return r.returncode == 0


# ---------------- tarefa agendada (proteção forte, admin) ----------------
def criar_tarefa():
    """Tarefa: ao fazer logon e a cada 1 min (se o guardião foi morto, volta),
    com privilégios mais altos. Precisa rodar como administrador."""
    prog, args = comando_guardiao()
    usuario = os.environ.get("USERDOMAIN", "") + "\\" + os.environ.get("USERNAME", "")
    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Bloqueador de conteudo sensivel</Description></RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{usuario}</UserId>
      <Repetition><Interval>PT1M</Interval><StopAtDurationEnd>false</StopAtDurationEnd></Repetition>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{usuario}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>5</Priority>
    <RestartOnFailure><Interval>PT1M</Interval><Count>999</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{prog}</Command>
      <Arguments>{args.replace('"', '&quot;')}</Arguments>
      <WorkingDirectory>{config.PASTA}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
    arq = os.path.join(config.DADOS, "tarefa.xml")
    with open(arq, "w", encoding="utf-16") as f:
        f.write(xml)
    r = subprocess.run(["schtasks", "/Create", "/TN", NOME_TAREFA, "/XML", arq, "/F"],
                       capture_output=True, text=True)
    os.remove(arq)
    if r.returncode != 0:
        raise RuntimeError((r.stdout + r.stderr).strip())


def remover_tarefa():
    subprocess.run(["schtasks", "/Delete", "/TN", NOME_TAREFA, "/F"],
                   capture_output=True)


def tarefa_existe():
    return subprocess.run(["schtasks", "/Query", "/TN", NOME_TAREFA],
                          capture_output=True, creationflags=0x08000000).returncode == 0
