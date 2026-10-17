"""
Bot do O Caça Preço
-------------------
Você manda uma oferta no privado do bot e ele publica formatada no canal.

Formato da mensagem (uma informação por linha, em qualquer ordem):

    Fone Bluetooth JBL Tune 520
    199,90
    129,90
    Frete grátis Full
    https://meli.la/xxxxxxx

- A primeira linha de texto vira o NOME do produto.
- Números viram preços: o menor é o preço atual, o maior é o "de".
  (Se mandar só um número, ele vira o preço atual.)
- O link (http...) é o seu link de afiliado.
- Outras linhas de texto viram vantagens (✅).
- Pode mandar com FOTO: coloque esse texto como legenda da foto.

Comandos no privado do bot:
    /start   mostra seu ID e as instruções
    /modelo  mostra um exemplo de mensagem
    teste ...  (começando a mensagem com "teste") só mostra a prévia, não publica

Roda sem servidor: o GitHub Actions executa este arquivo a cada poucos minutos.
Usa só a biblioteca padrão do Python (não precisa instalar nada).
"""

import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CANAL = os.environ.get("CANAL", "@ocacapreco").strip()
OWNER_ID = os.environ.get("OWNER_ID", "").strip()

RODAPE = "⚠️ Preço e estoque podem mudar a qualquer momento."
HASHTAG = "#ocacapreco"

MODELO = (
    "Mande assim (uma informação por linha):\n\n"
    "Fone Bluetooth JBL Tune 520\n"
    "199,90\n"
    "129,90\n"
    "Frete grátis Full\n"
    "https://meli.la/SEU-LINK\n\n"
    "• 1ª linha = nome do produto\n"
    "• números = preços (o maior vira o \"De\")\n"
    "• link = seu link de afiliado\n"
    "• outras linhas = vantagens\n"
    "• pode mandar uma FOTO com esse texto na legenda\n"
    "• comece com \"teste\" para ver a prévia sem publicar"
)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PRECO_RE = re.compile(r"^(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?$", re.IGNORECASE)


# ---------------------------------------------------------------- Telegram
def api(metodo, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    dados = urllib.parse.urlencode(
        {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in params.items() if v is not None}
    ).encode()
    try:
        with urllib.request.urlopen(url, data=dados, timeout=40) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        resp = json.loads(e.read().decode() or "{}")
    if not resp.get("ok"):
        raise RuntimeError(f"{metodo}: {resp.get('description', resp)}")
    return resp["result"]


# ---------------------------------------------------------------- Oferta
def ler_preco(linha):
    m = PRECO_RE.match(linha.strip().replace(" ", ""))
    if not m:
        return None
    inteiro = m.group(1).replace(".", "")
    centavos = (m.group(2) or "0").ljust(2, "0")
    return float(f"{inteiro}.{centavos}")


def reais(valor):
    s = f"{valor:,.2f}"  # 1,299.90
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def ler_oferta(texto):
    """Transforma a mensagem do dono em um dicionário com os dados da oferta."""
    nome, vantagens, precos, link = None, [], [], None
    for bruta in (texto or "").splitlines():
        linha = bruta.strip()
        if not linha:
            continue
        url = URL_RE.search(linha)
        if url and not link:
            link = url.group(0).rstrip(").,")
            resto = URL_RE.sub("", linha).strip(" -–:|")
            if not resto:
                continue
            linha = resto
        preco = ler_preco(linha)
        if preco is not None:
            precos.append(preco)
        elif nome is None:
            nome = linha
        else:
            vantagens.append(linha.lstrip("-•✅* ").strip())
    if not link:
        return None, "Não achei o link de afiliado (precisa começar com http)."
    if not nome:
        return None, "Faltou o nome do produto (escreva na primeira linha)."
    if not precos:
        return None, "Faltou o preço (ex.: 129,90)."
    precos = sorted(set(precos))
    return {
        "nome": nome,
        "por": precos[0],
        "de": precos[-1] if len(precos) > 1 else None,
        "vantagens": [v for v in vantagens if v],
        "link": link,
    }, None


def montar_post(o):
    e = html.escape
    partes = [f"🔥 <b>{e(o['nome'])}</b>", ""]
    if o["de"]:
        desconto = round((1 - o["por"] / o["de"]) * 100)
        partes.append(f"<s>De {reais(o['de'])}</s>")
        linha = f"💰 <b>Por {reais(o['por'])}</b>"
        if desconto >= 1:
            linha += f"  ({desconto}% OFF)"
        partes.append(linha)
    else:
        partes.append(f"💰 <b>Por {reais(o['por'])}</b>")
    if o["vantagens"]:
        partes.append("")
        partes += [f"✅ {e(v)}" for v in o["vantagens"]]
    partes += [
        "",
        f'👉 <a href="{e(o["link"], quote=True)}">Ver oferta no Mercado Livre</a>',
        "",
        RODAPE,
        HASHTAG,
    ]
    return "\n".join(partes)


# ---------------------------------------------------------------- Mensagens
def publicar(destino, post, foto_id):
    if foto_id:
        if len(post) > 1024:
            raise RuntimeError("Texto grande demais para legenda de foto. Tire algumas vantagens.")
        return api("sendPhoto", chat_id=destino, photo=foto_id, caption=post, parse_mode="HTML")
    return api("sendMessage", chat_id=destino, text=post, parse_mode="HTML")


def link_do_post(msg):
    chat = msg.get("chat", {})
    if chat.get("username"):
        return f"https://t.me/{chat['username']}/{msg['message_id']}"
    return None


def tratar(msg):
    chat_id = msg["chat"]["id"]
    de_quem = str(msg.get("from", {}).get("id", ""))
    texto = (msg.get("text") or msg.get("caption") or "").strip()
    responder = lambda t: api("sendMessage", chat_id=chat_id, text=t, disable_web_page_preview=True)

    if msg["chat"].get("type") != "private":
        return

    if not OWNER_ID:
        responder(
            f"Seu ID do Telegram é: {de_quem}\n\n"
            "Coloque esse número no segredo OWNER_ID do GitHub. "
            "Até lá eu não publico nada."
        )
        return
    if de_quem != OWNER_ID:
        responder("Este bot é privado. 🎯 Siga as ofertas em " + CANAL)
        return

    comando = texto.lower()
    if comando.startswith("/start"):
        responder(f"Olá! 🎯 Seu ID: {de_quem}\nCanal: {CANAL}\n\n" + MODELO)
        return
    if comando.startswith("/modelo") or comando.startswith("/ajuda") or comando.startswith("/help"):
        responder(MODELO)
        return

    so_teste = comando.startswith("teste")
    if so_teste:
        texto = texto[5:].lstrip(" :-\n")

    oferta, erro = ler_oferta(texto)
    if erro:
        responder("❌ " + erro + "\n\n" + MODELO)
        return

    foto_id = msg["photo"][-1]["file_id"] if msg.get("photo") else None
    post = montar_post(oferta)

    if so_teste:
        publicar(chat_id, post, foto_id)
        responder("👆 Prévia. Para publicar, mande de novo sem a palavra \"teste\".")
        return

    enviado = publicar(CANAL, post, foto_id)
    link = link_do_post(enviado)
    responder("✅ Publicado no canal!" + (f"\n{link}" if link else ""))


# ---------------------------------------------------------------- Execução
def main():
    if not TOKEN:
        sys.exit("Falta o segredo TELEGRAM_TOKEN.")
    atualizacoes = api("getUpdates", timeout=0, allowed_updates=["message"])
    print(f"{len(atualizacoes)} mensagem(ns) nova(s).")
    for upd in atualizacoes:
        msg = upd.get("message")
        if msg:
            try:
                tratar(msg)
            except Exception as e:  # avisa o dono e segue para a próxima
                print("Erro:", e)
                try:
                    api("sendMessage", chat_id=msg["chat"]["id"], text=f"❌ Não consegui publicar: {e}")
                except Exception:
                    pass
        # confirma a mensagem no Telegram para não processar de novo
        api("getUpdates", offset=upd["update_id"] + 1, timeout=0)


if __name__ == "__main__":
    main()
