"""Captura de tela: DXGI (dxcam, ~1 ms) com fallback para mss (~35 ms).
As duas respeitam WDA_EXCLUDEFROMCAPTURE (o overlay não aparece)."""
import time

import mss
import numpy as np


class Captura:
    def __init__(self, monitor):
        self.monitor = monitor
        self.ultimo = None
        self.dx = None
        self.sct = None
        self.erros_dx = 0
        try:
            import dxcam
            self.dx = dxcam.create(output_color="BGR")
            self.metodo = "dxcam"
        except Exception as e:
            print("dxcam indisponível, usando mss:", e)
            self._usar_mss()

    def _usar_mss(self):
        self.dx = None
        self.sct = mss.MSS()
        self.metodo = "mss"

    def pegar(self):
        """Retorna (frame BGR, mudou). Com dxcam, mudou=False quando a tela
        está parada (aí dá para pular a análise)."""
        if self.dx is not None:
            try:
                f = self.dx.grab()
                self.erros_dx = 0
                if f is None:
                    if self.ultimo is not None:
                        return self.ultimo, False
                    for _ in range(20):          # primeira captura
                        time.sleep(0.05)
                        f = self.dx.grab()
                        if f is not None:
                            break
                if f is not None:
                    self.ultimo = f
                    return f, True
            except Exception as e:
                self.erros_dx += 1
                print("Erro no dxcam:", repr(e))
                if self.erros_dx >= 5:
                    print("Trocando para mss.")
                    self._usar_mss()
                time.sleep(0.2)
                if self.ultimo is not None:
                    return self.ultimo, False
            if self.dx is not None and self.ultimo is None:
                self._usar_mss()
        if self.sct is None:
            self._usar_mss()
        f = np.ascontiguousarray(np.array(self.sct.grab(self.monitor))[:, :, :3])
        self.ultimo = f
        return f, True
