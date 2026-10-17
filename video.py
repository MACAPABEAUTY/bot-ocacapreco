"""Vídeo vertical (1080x1920, ~12s) de oferta para TikTok / Reels.

Cenas:
  0,0–2,3s  gancho em tela roxa ("OLHA ESSE PREÇO")
  2,0–9,2s  produto com zoom lento, nome, preço "De" e "Por", selo de desconto
  9,0–12s   tela final: link no perfil + canal

O texto fica longe das bordas de baixo e da direita, onde o TikTok põe botões e legenda.
Com voz configurada, sai narrado; no TikTok dá para somar um som em alta com volume baixo.
"""
import io
import os
import random
import re
import subprocess
import tempfile

from PIL import Image, ImageDraw

import arte

L, A = 1080, 1920
FPS = 30
DURACAO = 12.0
GANCHOS = ["OLHA ESSE PREÇO", "ACHADINHO DO DIA", "PARA DE PAGAR CARO", "CORRE QUE ACABA", "ACHEI NO MERCADO LIVRE"]


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _janela(t, ini, fim, entrada=0.35, saida=0.35):
    """Opacidade 0..1 de um elemento visível entre ini e fim."""
    if t < ini or t > fim:
        return 0.0
    return min(_ease((t - ini) / entrada) if entrada else 1.0,
               _ease((fim - t) / saida) if saida else 1.0)


def _camada():
    return Image.new("RGBA", (L, A), (0, 0, 0, 0))


def _centro(d, y, texto, f, cor):
    d.text((L / 2, y), texto, font=f, fill=cor, anchor="mm")


def _tela_gancho(gancho):
    img = Image.new("RGBA", (L, A), arte.ROXO)
    d = ImageDraw.Draw(img)
    arte.mira(d, L // 2, 560, 90, arte.LARANJA, 22)
    f = arte.fonte(132, 800)
    linhas = arte.quebrar(d, gancho, f, L - 160, 3)
    y = 860
    for i, linha in enumerate(linhas):
        _centro(d, y + i * 150, linha, f, arte.BRANCO if i < len(linhas) - 1 else arte.LARANJA)
    seta_y = y + len(linhas) * 150 + 10
    d.polygon([(L / 2 - 50, seta_y), (L / 2 + 50, seta_y), (L / 2, seta_y + 60)], fill=arte.BRANCO)
    return img


def _tela_final(telegram):
    img = Image.new("RGBA", (L, A), arte.ROXO)
    d = ImageDraw.Draw(img)
    arte.cabecalho(img, 300)
    d = ImageDraw.Draw(img)
    _centro(d, 700, "Quer o link?", arte.fonte(110, 800), arte.BRANCO)
    _centro(d, 830, "Tá no perfil", arte.fonte(110, 800), arte.LARANJA)
    _centro(d, 1010, "Ofertas novas todo dia", arte.fonte(58, 600), "#E4DCF5")
    d.rounded_rectangle([150, 1100, L - 150, 1240], radius=70, fill=arte.LARANJA)
    _centro(d, 1170, "Canal grátis no Telegram", arte.fonte(54, 800), arte.BRANCO)
    _centro(d, 1310, telegram, arte.fonte(50, 600), "#E4DCF5")
    return img


def _base_produto(oferta):
    """Fundo fixo da cena do produto (sem a foto, que anima)."""
    img = Image.new("RGBA", (L, A), arte.CREME)
    arte.cabecalho(img, 230)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([90, 300, L - 90, 1150], radius=48, fill=arte.BRANCO)
    f = arte.fonte(58, 700)
    for i, linha in enumerate(arte.quebrar(d, oferta["nome"], f, L - 200, 2)):
        _centro(d, 1220 + i * 70, linha, f, arte.ROXO_ESCURO)
    return img


def _camada_de(oferta):
    c = _camada()
    if not oferta.get("de"):
        return c
    d = ImageDraw.Draw(c)
    f = arte.fonte(64, 500)
    txt = "De " + arte.reais(oferta["de"])
    _centro(d, 1395, txt, f, arte.CINZA)
    w = d.textlength(txt, font=f)
    d.line([L / 2 - w / 2 - 8, 1398, L / 2 + w / 2 + 8, 1398], fill=arte.CINZA, width=6)
    return c


def _camada_por(oferta):
    c = _camada()
    d = ImageDraw.Draw(c)
    f_rot, f_val = arte.fonte(56, 600), arte.fonte(132, 800)
    valor = arte.reais(oferta["por"])
    w_rot, w_val = d.textlength("por ", font=f_rot), d.textlength(valor, font=f_val)
    x = L / 2 - (w_rot + w_val) / 2
    d.text((x, 1560), "por ", font=f_rot, fill=arte.ROXO_ESCURO, anchor="ls")
    d.text((x + w_rot, 1560), valor, font=f_val, fill=arte.LARANJA, anchor="ls")
    return c


def _camada_selo(desconto):
    c = _camada()
    if desconto and desconto > 0:
        arte.selo_desconto(c, 830, 360, 120, desconto)
    return c


def _misturar(fundo, camada, alfa, dy=0, escala=1.0):
    if alfa <= 0:
        return
    if escala != 1.0:
        w, h = int(L * escala), int(A * escala)
        camada = camada.resize((w, h), Image.BILINEAR)
        tmp = _camada()
        tmp.paste(camada, ((L - w) // 2, (A - h) // 2))
        camada = tmp
    if dy:
        tmp = _camada()
        tmp.paste(camada, (0, int(dy)))
        camada = tmp
    if alfa < 1:
        r, g, b, a = camada.split()
        a = a.point(lambda v: int(v * alfa))
        camada = Image.merge("RGBA", (r, g, b, a))
    fundo.alpha_composite(camada)


def _foto_preparada(foto_bytes):
    if not foto_bytes:
        return None
    try:
        f = Image.open(io.BytesIO(foto_bytes)).convert("RGBA")
    except Exception:
        return None
    caixa_w, caixa_h = L - 180 - 120, 850 - 120
    escala = min(caixa_w / f.width, caixa_h / f.height)
    return f.resize((max(1, int(f.width * escala)), max(1, int(f.height * escala))), Image.LANCZOS)


def nome_falado(nome, max_palavras=5):
    """Tira códigos de modelo (ex.: Aq-230a-1dmq) para a voz não soletrar."""
    palavras = [p for p in nome.split()
                if not (re.search(r"\d", p) and re.search(r"[A-Za-z]", p)) and not re.fullmatch(r"[-–|/+]", p)]
    return " ".join(palavras[:max_palavras])


def valor_falado(v):
    reais_, cent = int(v), int(round((v - int(v)) * 100))
    if cent == 100:
        reais_, cent = reais_ + 1, 0
    txt = f"{reais_} rea{'l' if reais_ == 1 else 'is'}"
    return txt + (f" e {cent} centavo{'s' if cent != 1 else ''}" if cent else "")


def texto_narracao(oferta, gancho, desconto):
    partes = [gancho.capitalize() + "!", nome_falado(oferta["nome"]) + "."]
    if oferta.get("de"):
        partes.append(f"De {valor_falado(oferta['de'])}, por apenas {valor_falado(oferta['por'])}.")
    else:
        partes.append(f"Por apenas {valor_falado(oferta['por'])}.")
    if desconto and desconto >= 10:
        partes.append(f"São {desconto} por cento de desconto!")
    partes.append("Quer o link? Tá no perfil. Segue o Caça Preço!")
    return " ".join(partes)


def falar(texto, voz, velocidade="+8%", tom="+0Hz"):
    """Gera a narração (MP3) com as vozes neurais do Edge. Devolve None se falhar."""
    try:
        import asyncio
        import edge_tts

        async def _rodar():
            com = edge_tts.Communicate(texto, voz, rate=velocidade, pitch=tom)
            dados = b""
            async for parte in com.stream():
                if parte["type"] == "audio":
                    dados += parte["data"]
            return dados

        audio = asyncio.run(asyncio.wait_for(_rodar(), timeout=60))
        return audio or None
    except Exception as e:
        print("Narração falhou:", e)
        return None


def _duracao_audio(caminho):
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", caminho], capture_output=True, text=True, timeout=30)
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def gerar(oferta, foto_bytes, telegram="t.me/ocacapreco", gancho=None, voz=None, info=None,
          velocidade="+8%", tom="+0Hz"):
    """Retorna o MP4 (bytes). oferta = {nome, por, de, desconto}.
    voz: nome de voz do Edge (ex.: pt-BR-FranciscaNeural) para narrar; None = sem voz.
    info: dict opcional que recebe {"voz": True/False}."""
    desconto = oferta.get("desconto")
    if desconto is None and oferta.get("de"):
        desconto = round((1 - oferta["por"] / oferta["de"]) * 100)
    gancho = gancho or random.choice(GANCHOS)

    t_gancho, t_final = _tela_gancho(gancho), _tela_final(telegram)
    base = _base_produto(oferta)
    c_de, c_por, c_selo = _camada_de(oferta), _camada_por(oferta), _camada_selo(desconto)
    foto = _foto_preparada(foto_bytes)
    cx, cy = L // 2, 725  # centro do cartão

    with tempfile.TemporaryDirectory() as tmp:
        saida = os.path.join(tmp, "video.mp4")
        duracao, audio_path = DURACAO, None
        if voz:
            audio = falar(texto_narracao(oferta, gancho, desconto), voz, velocidade, tom)
            if audio:
                audio_path = os.path.join(tmp, "voz.mp3")
                with open(audio_path, "wb") as f:
                    f.write(audio)
                duracao = max(DURACAO, min(25.0, _duracao_audio(audio_path) + 1.0))
        if info is not None:
            info["voz"] = bool(audio_path)
        t_fim = duracao - 3.0  # tela final nos últimos 3 segundos
        if audio_path:
            entrada_audio = ["-i", audio_path]
            filtro = ["-filter_complex", f"[1:a]adelay=300|300,apad,atrim=0:{duracao}[a]", "-map", "0:v", "-map", "[a]"]
        else:
            entrada_audio = ["-f", "lavfi", "-t", str(duracao), "-i", "anullsrc=r=44100:cl=stereo"]
            filtro = ["-map", "0:v", "-map", "1:a"]
        cmd = ["ffmpeg", "-y", "-loglevel", "error",
               "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{L}x{A}", "-r", str(FPS), "-i", "-",
               *entrada_audio, *filtro, "-t", str(duracao),
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", saida]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:
            for n in range(int(duracao * FPS)):
                t = n / FPS
                quadro = base.copy()
                if foto is not None:  # zoom lento (Ken Burns)
                    z = 1.0 + 0.10 * (t / duracao)
                    fw, fh = int(foto.width * z), int(foto.height * z)
                    f = foto.resize((fw, fh), Image.BILINEAR)
                    quadro.paste(f, (cx - fw // 2, cy - fh // 2), f)
                _misturar(quadro, c_de, _janela(t, 3.0, 99, 0.4, 0.01), dy=(1 - _ease((t - 3.0) / 0.4)) * 30)
                p = _ease((t - 4.0) / 0.35)
                _misturar(quadro, c_por, _janela(t, 4.0, 99, 0.25, 0.01), escala=0.9 + 0.1 * p if p < 1 else 1.0)
                _misturar(quadro, c_selo, _janela(t, 5.2, 99, 0.3, 0.01), dy=(1 - _ease((t - 5.2) / 0.3)) * -40)
                _misturar(quadro, t_gancho, 1.0 if t < 2.0 else _janela(t, 0, 2.4, 0.01, 0.4))
                _misturar(quadro, t_final, _janela(t, t_fim, 99, 0.4, 0.01))
                proc.stdin.write(quadro.convert("RGB").tobytes())
        finally:
            proc.stdin.close()
            proc.wait()
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg falhou ao gerar o vídeo")
        with open(saida, "rb") as f:
            return f.read()


def legenda_tiktok(oferta):
    nome = oferta["nome"]
    curto = " ".join(nome.split()[:6])
    preco = arte.reais(oferta["por"])
    de = f" (era {arte.reais(oferta['de'])})" if oferta.get("de") else ""
    return (f"Achei {curto} por {preco}{de} 😱 Link no perfil 🔗\n\n"
            "#achadinhos #mercadolivre #ofertas #promocao #achadinhosdodia #ocacapreco")
