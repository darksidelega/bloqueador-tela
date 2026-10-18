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


def restrito_ate():
    """Até quando o modo restrito vale (epoch), ou 0 se desligado."""
    ate = _ler(ARQ_RESTRITO, "restrito")
    reg = _registro()
    if reg:
        try:
            if hmac.compare_digest(reg["assinatura"], _assinatura("restrito", reg["ate"])):
                ate = max(ate, reg["ate"])
        except Exception:
            pass
    return ate if ate > time.time() else 0


def restrito_ativo():
    return restrito_ate() > 0


def ativar_restrito(minutos):
    """Liga (ou estende) o modo restrito. Nunca encurta."""
    ate = int(max(restrito_ate(), time.time() + minutos * 60))
    _gravar(ARQ_RESTRITO, "restrito", ate)
    _registro({"ate": ate, "assinatura": _assinatura("restrito", ate)})
    cancelar_pausa()
    return ate


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


def iniciar_guardiao():
    prog, args = comando_guardiao()
    subprocess.Popen(f'"{prog}" {args}', cwd=config.PASTA,
                     creationflags=SEM_JANELA | 0x00000008)  # separado


def iniciar_app():
    subprocess.Popen([pythonw(), script("bloqueador_tela.py")], cwd=config.PASTA,
                     creationflags=SEM_JANELA | 0x00000008)


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
