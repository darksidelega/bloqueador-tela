"""Gera o ícone do app (escudo com mosaico). Rode uma vez: python gerar_icone.py"""
import os

from PIL import Image, ImageDraw, ImageFilter

PASTA = os.path.dirname(os.path.abspath(__file__))
N = 1024  # desenha grande e reduz (bordas lisas)


def gradiente(w, h, c1, c2):
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            t = (x + y) / (w + h - 2)
            px[x, y] = tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))
    return img


def desenhar():
    fundo = gradiente(N // 8, N // 8, (99, 102, 241), (20, 184, 166)).resize((N, N), Image.BICUBIC)
    mascara = Image.new("L", (N, N), 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, N - 1, N - 1), radius=int(N * 0.23), fill=255)
    img = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    img.paste(fundo, (0, 0), mascara)

    # escudo branco (lados retos e base curva até a ponta)
    cx, topo, larg = N / 2, N * 0.16, N * 0.60
    esq, dir_ = cx - larg / 2, cx + larg / 2
    pontos = [(esq, topo + N * 0.07), (cx, topo), (dir_, topo + N * 0.07), (dir_, N * 0.48)]
    for k in range(1, 21):                  # curva direita até a ponta
        t = k / 20
        x = (1 - t) ** 2 * dir_ + 2 * (1 - t) * t * dir_ + t * t * cx
        y = (1 - t) ** 2 * N * 0.48 + 2 * (1 - t) * t * N * 0.72 + t * t * N * 0.86
        pontos.append((x, y))
    for x, y in reversed(pontos[4:-1]):     # espelha para a esquerda
        pontos.append((2 * cx - x, y))
    pontos.append((esq, N * 0.48))
    esc = Image.new("L", (N, N), 0)
    ImageDraw.Draw(esc).polygon(pontos, fill=255)
    sombra = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    sombra.putalpha(esc.filter(ImageFilter.GaussianBlur(N * 0.025)).point(lambda v: v * 0.35))
    camada = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    camada.paste(sombra, (0, int(N * 0.02)))
    img = Image.alpha_composite(img, camada)
    img.paste((255, 255, 255, 255), (0, 0), esc)
    img.putalpha(Image.composite(img.getchannel("A"), Image.new("L", (N, N), 0), mascara))

    # mosaico 3x3 dentro do escudo (o "pixelado" da TV japonesa)
    d = ImageDraw.Draw(img)
    lado, gap = N * 0.105, N * 0.018
    x0 = cx - (3 * lado + 2 * gap) / 2
    y0 = N * 0.29
    cores = [(99, 102, 241), (59, 130, 246), (20, 184, 166),
             (59, 130, 246), (20, 184, 166), (99, 102, 241),
             (20, 184, 166), (99, 102, 241), (59, 130, 246)]
    for i in range(3):
        for j in range(3):
            x, y = x0 + j * (lado + gap), y0 + i * (lado + gap)
            d.rounded_rectangle((x, y, x + lado, y + lado), radius=N * 0.018, fill=cores[i * 3 + j])
    return img


if __name__ == "__main__":
    img = desenhar()
    img.resize((256, 256), Image.LANCZOS).save(os.path.join(PASTA, "icone.png"))
    img.resize((256, 256), Image.LANCZOS).save(
        os.path.join(PASTA, "icone.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok")
