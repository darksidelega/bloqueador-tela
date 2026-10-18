"""Atalhos do Painel (Área de Trabalho e Menu Iniciar) com ícone próprio.

O atalho e a janela do Painel usam o mesmo AppUserModelID: assim, quando você
fixa o Painel na barra de tarefas, o Windows fixa este atalho (com o ícone
do app) e não o Python.
"""
import os

from . import config, protecao

APP_ID = "BloqueadorTela.Painel"
NOME = "Bloqueador de Tela.lnk"
ICONE = os.path.join(config.APP, "recursos", "icone.ico")


def _pasta(csidl):
    from win32com.shell import shell
    return shell.SHGetFolderPath(0, csidl, None, 0)


def desktop():
    from win32com.shell import shellcon
    return os.path.join(_pasta(shellcon.CSIDL_DESKTOPDIRECTORY), NOME)


def menu_iniciar():
    from win32com.shell import shellcon
    return os.path.join(_pasta(shellcon.CSIDL_PROGRAMS), NOME)


def criar(caminho):
    import pythoncom
    from win32com.propsys import propsys, pscon
    from win32com.shell import shell
    lnk = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                     pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
    lnk.SetPath(protecao.pythonw())
    lnk.SetArguments(f'"{protecao.script("painel.py")}"')
    lnk.SetWorkingDirectory(config.PASTA)
    lnk.SetIconLocation(ICONE, 0)
    lnk.SetDescription("Painel do Bloqueador de Tela")
    props = lnk.QueryInterface(propsys.IID_IPropertyStore)
    props.SetValue(pscon.PKEY_AppUserModel_ID, propsys.PROPVARIANTType(APP_ID))
    props.Commit()
    lnk.QueryInterface(pythoncom.IID_IPersistFile).Save(caminho, 0)


def fixar_no_iniciar(caminho):
    """Fixa no Menu Iniciar (a barra de tarefas o Windows não deixa por código)."""
    import win32com.client
    sh = win32com.client.Dispatch("Shell.Application")
    item = sh.Namespace(os.path.dirname(caminho)).ParseName(os.path.basename(caminho))
    for verbo in item.Verbs():
        nome = verbo.Name.replace("&", "").lower()
        if nome in ("fixar em iniciar", "pin to start"):
            verbo.DoIt()
            return True
    return False


def existe():
    try:
        return os.path.isfile(menu_iniciar()) or os.path.isfile(desktop())
    except Exception:
        return False
