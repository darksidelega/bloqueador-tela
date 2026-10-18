"""Autoproteção: senha para fechar/pausar, instância única, tarefa agendada.

A senha fica só como hash (PBKDF2) em senha.json. Fechar com a senha cria
uma "pausa" assinada até um horário; enquanto ela vale, o guardião não
reinicia o bloqueador.
"""
import ctypes
import hashlib
import hmac
import json
import os
import secrets
import subprocess
import sys
import time

from . import config

ARQ_SENHA = os.path.join(config.DADOS, "senha.json")
ARQ_PAUSA = os.path.join(config.DADOS, "pausa.json")
NOME_TAREFA = "BloqueadorTela"
kernel32 = ctypes.windll.kernel32


# ---------------- senha ----------------
def _hash(senha, sal):
    return hashlib.pbkdf2_hmac("sha256", senha.encode(), bytes.fromhex(sal), 200_000).hex()


def tem_senha():
    return os.path.isfile(ARQ_SENHA)


def definir_senha(senha):
    sal = secrets.token_hex(16)
    with open(ARQ_SENHA, "w", encoding="utf-8") as f:
        json.dump({"sal": sal, "hash": _hash(senha, sal)}, f)


def _dados_senha():
    with open(ARQ_SENHA, encoding="utf-8") as f:
        return json.load(f)


def verificar_senha(senha):
    if not tem_senha():
        return True
    d = _dados_senha()
    time.sleep(0.5)  # atrasa tentativas em sequência
    return hmac.compare_digest(_hash(senha, d["sal"]), d["hash"])


# ---------------- pausa ----------------
def _assinatura(ate):
    chave = _dados_senha()["hash"] if tem_senha() else "sem-senha"
    return hmac.new(chave.encode(), str(ate).encode(), "sha256").hexdigest()


def pausar(minutos):
    ate = int(time.time() + minutos * 60)
    with open(ARQ_PAUSA, "w", encoding="utf-8") as f:
        json.dump({"ate": ate, "assinatura": _assinatura(ate)}, f)


def pausa_ativa():
    try:
        with open(ARQ_PAUSA, encoding="utf-8") as f:
            d = json.load(f)
        return (time.time() < d["ate"] and
                hmac.compare_digest(d["assinatura"], _assinatura(d["ate"])))
    except Exception:
        return False


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


def pausa_ate():
    try:
        with open(ARQ_PAUSA, encoding="utf-8") as f:
            return json.load(f)["ate"] if pausa_ativa() else 0
    except Exception:
        return 0


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
