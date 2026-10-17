"""
Gera as artes do O Caça Preço para cada oferta:
  - story  (1080 x 1920)  -> stories do Instagram / status do WhatsApp
  - post   (1080 x 1350)  -> feed do Instagram
"""

import io
import os

from PIL import Image, ImageDraw, ImageFont

AQUI = os.path.dirname(os.path.abspath(__file__))
FONTE = os.path.join(AQUI, "fonts", "BricolageGrotesque.ttf")

ROXO = "#3B1F6E"
ROXO_ESCURO = "#2A1650"
LARANJA = "#E8590C"
CREME = "#F6F1E7"
CINZA = "#6B5A8C"
BRANCO = "#FFFFFF"


def fonte(tamanho, peso=800):
    f = ImageFont.truetype(FONTE, tamanho)
    try:
        f.set_variation_by_axes([min(96, max(12, tamanho)), peso, 100])
    except Exception:
        pass
    return f


def reais(v):
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def quebrar(d, texto, f, largura, max_linhas):
    palavras, linhas, atual = texto.split(), [], ""
    for p in palavras:
        teste = (atual + " " + p).strip()
        if d.textlength(teste, font=f) <= largura:
            atual = teste
        else:
            if atual:
                linhas.append(atual)
            atual = p
    if atual:
        linhas.append(atual)
    if len(linhas) > max_linhas:
        linhas = linhas[:max_linhas]
        ult = linhas[-1]
        while d.textlength(ult + "…", font=f) > largura and " " in ult:
            ult = ult.rsplit(" ", 1)[0]
        linhas[-1] = ult + "…"
    return linhas


def mira(d, cx, cy, r, cor, esp):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=cor, width=esp)
    braco = int(r * 0.75)
    for (x1, y1, x2, y2) in [
        (cx, cy - r - braco, cx, cy - r + esp), (cx, cy + r - esp, cx, cy + r + braco),
        (cx - r - braco, cy, cx - r + esp, cy), (cx + r - esp, cy, cx + r + braco, cy),
    ]:
        d.line([x1, y1, x2, y2], fill=cor, width=esp)
    for (x, y) in [(cx, cy - r - braco), (cx, cy + r + braco), (cx - r - braco, cy), (cx + r + braco, cy)]:
        d.ellipse([x - esp / 2, y - esp / 2, x + esp / 2, y + esp / 2], fill=cor)


def cabecalho(img, altura):
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, img.width, altura], fill=ROXO)
    f_o = fonte(int(altura * 0.2), 500)
    f_nome = fonte(int(altura * 0.42), 800)
    r = int(altura * 0.17)
    w_caca = d.textlength("caça", font=f_nome)
    w_preco = d.textlength("preço", font=f_nome)
    w_total = r * 2 + int(r * 1.6) + 28 + w_caca + w_preco
    x = (img.width - w_total) / 2
    cy = altura / 2
    mira(d, x + r + int(r * 0.8), cy, r, LARANJA, max(6, r // 4))
    x += r * 2 + int(r * 1.6) + 28
    d.text((x, cy - altura * 0.05), "O", font=f_o, fill=BRANCO, anchor="ls")
    d.text((x, cy + altura * 0.28), "caça", font=f_nome, fill=BRANCO, anchor="ls")
    d.text((x + w_caca, cy + altura * 0.28), "preço", font=f_nome, fill=LARANJA, anchor="ls")


def cartao_produto(img, caixa, foto):
    d = ImageDraw.Draw(img)
    x1, y1, x2, y2 = caixa
    d.rounded_rectangle(caixa, radius=44, fill=BRANCO)
    if foto is None:
        return
    margem = 48
    w, h = x2 - x1 - 2 * margem, y2 - y1 - 2 * margem
    f = foto.convert("RGBA")
    f.thumbnail((w, h), Image.LANCZOS)
    if f.width < w * 0.7 and f.height < h * 0.7:  # foto pequena: amplia um pouco
        escala = min(w * 0.85 / f.width, h * 0.85 / f.height)
        f = f.resize((int(f.width * escala), int(f.height * escala)), Image.LANCZOS)
    img.paste(f, (x1 + margem + (w - f.width) // 2, y1 + margem + (h - f.height) // 2), f)


def selo_desconto(img, cx, cy, r, desconto):
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=LARANJA)
    d.text((cx, cy - r * 0.08), f"-{desconto}%", font=fonte(int(r * 0.62), 800), fill=BRANCO, anchor="mm")
    d.text((cx, cy + r * 0.45), "OFF", font=fonte(int(r * 0.3), 700), fill=BRANCO, anchor="mm")


def botao(img, y, altura, texto):
    d = ImageDraw.Draw(img)
    f = fonte(int(altura * 0.36), 700)
    w = d.textlength(texto, font=f) + altura * 1.2
    x = (img.width - w) / 2
    d.rounded_rectangle([x, y, x + w, y + altura], radius=altura // 2, fill=ROXO)
    d.text((img.width / 2, y + altura / 2), texto, font=f, fill=BRANCO, anchor="mm")


def precos(img, y, oferta, t_de, t_por):
    d = ImageDraw.Draw(img)
    cx = img.width / 2
    if oferta.get("de"):
        f_de = fonte(t_de, 500)
        txt = "De " + reais(oferta["de"])
        d.text((cx, y), txt, font=f_de, fill=CINZA, anchor="mt")
        w = d.textlength(txt, font=f_de)
        meio = y + t_de * 0.55
        d.line([cx - w / 2 - 6, meio, cx + w / 2 + 6, meio], fill=CINZA, width=max(3, t_de // 12))
        y += int(t_de * 1.35)
    f_por = fonte(t_por, 800)
    rotulo = "por "
    f_rot = fonte(int(t_por * 0.4), 600)
    valor = reais(oferta["por"])
    w_rot, w_val = d.textlength(rotulo, font=f_rot), d.textlength(valor, font=f_por)
    x = cx - (w_rot + w_val) / 2
    base = y + t_por * 0.85
    d.text((x, base), rotulo, font=f_rot, fill=ROXO_ESCURO, anchor="ls")
    d.text((x + w_rot, base), valor, font=f_por, fill=LARANJA, anchor="ls")
    return int(base + t_por * 0.25)


def gerar(oferta, foto_bytes=None, formato="story", telegram="t.me/ocacapreco"):
    """Retorna PNG (bytes). oferta = {nome, por, de (opcional)}"""
    W, H = (1080, 1920) if formato == "story" else (1080, 1350)
    img = Image.new("RGB", (W, H), CREME)
    foto = None
    if foto_bytes:
        try:
            foto = Image.open(io.BytesIO(foto_bytes))
        except Exception:
            foto = None

    if formato == "story":
        topo, card, t_nome, linhas, t_de, t_por, bt = 250, (90, 330, 990, 1180), 56, 3, 46, 128, 110
    else:
        topo, card, t_nome, linhas, t_de, t_por, bt = 170, (150, 220, 930, 780), 46, 2, 38, 96, 88

    cabecalho(img, topo)
    cartao_produto(img, card, foto)
    desconto = 0
    if oferta.get("de"):
        desconto = round((1 - oferta["por"] / oferta["de"]) * 100)
    if desconto >= 1:
        r = 105 if formato == "story" else 85
        selo_desconto(img, card[2] - r * 0.55, card[1] + r * 0.55, r, desconto)

    d = ImageDraw.Draw(img)
    f_nome = fonte(t_nome, 600)
    y = card[3] + (52 if formato == "story" else 36)
    for linha in quebrar(d, oferta["nome"], f_nome, W - 160, linhas):
        d.text((W / 2, y), linha, font=f_nome, fill=ROXO_ESCURO, anchor="mt")
        y += int(t_nome * 1.22)
    y += 22 if formato == "story" else 12
    precos(img, y, oferta, t_de, t_por)

    botao(img, H - bt - (90 if formato == "story" else 50), bt, f"OFERTA NO TELEGRAM  ·  {telegram}")

    saida = io.BytesIO()
    img.save(saida, "PNG", optimize=True)
    return saida.getvalue()


def legenda_instagram(oferta, telegram="t.me/ocacapreco", palavra=None):
    linhas = [f"🔥 {oferta['nome']}", ""]
    if oferta.get("de"):
        desconto = round((1 - oferta["por"] / oferta["de"]) * 100)
        linhas.append(f"De {reais(oferta['de'])} por {reais(oferta['por'])} ({desconto}% OFF) 😱")
    else:
        linhas.append(f"Por apenas {reais(oferta['por'])} 😱")
    if palavra:
        linhas += ["", f"💬 Comente {palavra} que eu te mando o link no Direct! 📩"]
    linhas += [
        "",
        "👉 Mais ofertas todo dia no nosso canal do Telegram (link na bio).",
        f"🎯 {telegram}",
        "",
        "⚠️ Preço pode mudar a qualquer momento.",
        "",
        "#achadinhos #ofertas #promocao #descontos #ocacapreco",
    ]
    return "\n".join(linhas)
