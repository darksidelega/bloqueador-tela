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

ARQ_SENHA = config.caminho("senha.json")
ARQ_PAUSA = config.caminho("pausa.json")
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


# ---------------- tarefa agendada ----------------
def pythonw():
    exe = sys.executable
    w = os.path.join(os.path.dirname(exe), "pythonw.exe")
    return w if os.path.isfile(w) else exe


def comando_guardiao():
    """(programa, argumentos) para iniciar o guardião."""
    if getattr(sys, "frozen", False):
        return sys.executable, "--guardiao"
    return pythonw(), f'"{config.caminho("guardiao.py")}"'


def iniciar_guardiao():
    prog, args = comando_guardiao()
    subprocess.Popen(f'"{prog}" {args}', cwd=config.PASTA,
                     creationflags=0x08000000 | 0x00000008)  # sem janela, separado


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
    arq = config.caminho("tarefa.xml")
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
