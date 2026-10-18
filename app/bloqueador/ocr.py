"""OCR leve com o motor nativo do Windows (Windows.Media.Ocr), 100% local.
Procura palavras proibidas visíveis na tela.

Obs: o winrt é importado só dentro do LeitorTela, porque se for carregado
antes do onnxruntime a DLL do onnxruntime falha ao iniciar."""
import asyncio
import re

import cv2
import numpy as np


class LeitorTela:
    def __init__(self, largura_max=1600):
        global BitmapPixelFormat, SoftwareBitmap, DataWriter
        try:
            from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.storage.streams import DataWriter
        except ImportError:
            raise RuntimeError("OCR indisponível (pacotes winrt não instalados)")
        self.motor = OcrEngine.try_create_from_user_profile_languages()
        if self.motor is None:
            raise RuntimeError("Nenhum idioma de OCR instalado no Windows")
        self.largura_max = largura_max
        self.loop = asyncio.new_event_loop()

    def ler(self, frame):
        """frame BGR -> texto em minúsculas."""
        h, w = frame.shape[:2]
        if w > self.largura_max:
            f = self.largura_max / w
            frame = cv2.resize(frame, (self.largura_max, int(h * f)),
                               interpolation=cv2.INTER_AREA)
        bgra = np.ascontiguousarray(cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA))
        h, w = bgra.shape[:2]
        escritor = DataWriter()
        escritor.write_bytes(bgra.tobytes())
        bmp = SoftwareBitmap.create_copy_from_buffer(
            escritor.detach_buffer(), BitmapPixelFormat.BGRA8, w, h)
        resultado = self.loop.run_until_complete(self.motor.recognize_async(bmp))
        return resultado.text.lower()


def achar_palavras(texto, palavras):
    """Palavras inteiras, aceitando plural (evita 'sexta' casar com 'sex' e
    'pornomes' com 'porno')."""
    achadas = []
    for p in palavras:
        if re.search(r"(?<![^\W_])" + re.escape(p.lower()) + r"s?(?![^\W_])", texto):
            achadas.append(p)
    return achadas
