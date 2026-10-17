"""
Bot do O Caça Preço — versão 2
==============================

O que ele faz:
1. BUSCA OFERTAS (2x por dia, ou quando você manda /buscar): olha os mais vendidos
   das categorias do config.json pela API oficial do Mercado Livre e te manda, no
   privado, os que estão com desconto bom.
2. Você abre o produto, toca em Compartilhar › Copiar link e RESPONDE a sugestão
   colando o link meli.la. O bot publica no canal com foto, preço e o seu link.
3. Para cada oferta publicada, o bot te manda as ARTES prontas (story e post do
   Instagram) e a legenda.
4. Continua aceitando oferta manual (nome, preços e link em linhas separadas).

Comandos no privado: /start /modelo /conectar /buscar /status /diagnostico
"""

import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)

import arte  # noqa: E402
import ml    # noqa: E402
import instagram  # noqa: E402

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
OWNER_ID = os.environ.get("OWNER_ID", "").strip()
MODO = os.environ.get("MODO", "mensagens").strip() or "mensagens"
STATE_DIR = os.environ.get("STATE_DIR", os.path.join(AQUI, "state"))
ml.STATE_DIR = STATE_DIR
ml.TOKEN_FILE = os.path.join(STATE_DIR, "ml_token.enc")

with open(os.path.join(AQUI, "config.json"), encoding="utf-8") as _f:
    CFG = json.load(_f)
CANAL = os.environ.get("CANAL") or CFG.get("canal", "@ocacapreco")
TELEGRAM_LINK = "t.me/" + CANAL.lstrip("@")

RODAPE = "⚠️ Preço e estoque podem mudar a qualquer momento."
HASHTAG = "#ocacapreco"

MODELO = (
    "📌 JEITO 1 · Sugestões automáticas\n"
    "Eu te mando ofertas 2x por dia. Toque em \"Abrir produto\", depois em "
    "Compartilhar › Copiar link, e RESPONDA a sugestão colando o link.\n"
    "Na resposta você pode adicionar vantagens, uma por linha (ex.: Frete grátis).\n\n"
    "📌 JEITO 2 · Oferta manual (uma informação por linha):\n\n"
    "Fone Bluetooth JBL Tune 520\n"
    "199,90\n"
    "129,90\n"
    "Frete grátis Full\n"
    "https://meli.la/SEU-LINK\n\n"
    "• pode mandar com FOTO (texto na legenda)\n"
    "• comece com \"teste\" para ver só a prévia\n\n"
    "Comandos: /buscar /status /conectar /diagnostico /instagram"
)

URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
PRECO_RE = re.compile(r"^(?:r\$\s*)?(\d{1,3}(?:\.\d{3})*|\d+)(?:,(\d{1,2}))?$", re.IGNORECASE)
ID_RE = re.compile(r"🆔\s*(MLB\w+)")
CODIGO_RE = re.compile(r"(TG-[A-Za-z0-9-]+)")


# ================================================================ Telegram
def api(metodo, arquivos=None, **params):
    url = f"https://api.telegram.org/bot{TOKEN}/{metodo}"
    campos = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v)) for k, v in params.items() if v is not None}
    if arquivos:
        limite = uuid.uuid4().hex
        partes = []
        for k, v in campos.items():
            partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
        for k, (nome, conteudo) in arquivos.items():
            partes.append(
                f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"; filename=\"{nome}\"\r\n"
                f"Content-Type: application/octet-stream\r\n\r\n".encode() + conteudo + b"\r\n")
        partes.append(f"--{limite}--\r\n".encode())
        req = urllib.request.Request(url, data=b"".join(partes),
                                     headers={"Content-Type": f"multipart/form-data; boundary={limite}"})
    else:
        req = urllib.request.Request(url, data=urllib.parse.urlencode(campos).encode())
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        resp = json.loads(e.read().decode() or "{}")
    if not resp.get("ok"):
        raise RuntimeError(f"{metodo}: {resp.get('description', resp)}")
    return resp["result"]


def enviar(chat_id, texto, **extra):
    return api("sendMessage", chat_id=chat_id, text=texto, parse_mode="HTML",
               disable_web_page_preview=True, **extra)


def baixar(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ocacapreco-bot"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()
    except Exception as e:
        print("Não baixei a imagem:", e)
        return None


def foto_do_telegram(file_id):
    try:
        info = api("getFile", file_id=file_id)
        return baixar(f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}")
    except Exception as e:
        print("Não baixei a foto:", e)
        return None


# ================================================================ Estado (pasta state/)
def ler_json(nome, padrao):
    caminho = os.path.join(STATE_DIR, nome)
    try:
        with open(caminho, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return padrao


def salvar_json(nome, dados):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, nome), "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1, sort_keys=True)


# ================================================================ Oferta
def ler_preco(linha):
    m = PRECO_RE.match(linha.strip().replace(" ", ""))
    if not m:
        return None
    return float(f"{m.group(1).replace('.', '')}.{(m.group(2) or '0').ljust(2, '0')}")


def reais(v):
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def separar_link(texto):
    """Devolve (link, outras linhas)."""
    link, resto = None, []
    for bruta in (texto or "").splitlines():
        linha = bruta.strip()
        if not linha:
            continue
        url = URL_RE.search(linha)
        if url and not link:
            link = url.group(0).rstrip(").,")
            linha = URL_RE.sub("", linha).strip(" -–:|")
            if not linha:
                continue
        resto.append(linha)
    return link, resto


def ler_oferta(texto):
    link, linhas = separar_link(texto)
    nome, vantagens, precos = None, [], []
    for linha in linhas:
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
    return {"nome": nome, "por": precos[0], "de": precos[-1] if len(precos) > 1 else None,
            "vantagens": [v for v in vantagens if v], "link": link}, None


def montar_post(o):
    e = html.escape
    partes = [f"🔥 <b>{e(o['nome'])}</b>", ""]
    if o.get("de"):
        desconto = round((1 - o["por"] / o["de"]) * 100)
        partes.append(f"<s>De {reais(o['de'])}</s>")
        linha = f"💰 <b>Por {reais(o['por'])}</b>"
        if desconto >= 1:
            linha += f"  ({desconto}% OFF)"
        partes.append(linha)
    else:
        partes.append(f"💰 <b>Por {reais(o['por'])}</b>")
    if o.get("vantagens"):
        partes.append("")
        partes += [f"✅ {e(v)}" for v in o["vantagens"]]
    partes += ["", f'👉 <a href="{e(o["link"], quote=True)}">Ver oferta no Mercado Livre</a>', "", RODAPE, HASHTAG]
    return "\n".join(partes)


def publicar(destino, post, foto):
    """foto pode ser file_id do Telegram ou URL de imagem."""
    if foto:
        try:
            if len(post) > 1024:
                raise RuntimeError("legenda longa")
            return api("sendPhoto", chat_id=destino, photo=foto, caption=post, parse_mode="HTML")
        except RuntimeError as e:
            print("Foto falhou, publicando só texto:", e)
    return api("sendMessage", chat_id=destino, text=post, parse_mode="HTML")


def enviar_artes(chat_id, oferta, foto_bytes):
    """Manda story, post do feed e legenda do Instagram para o dono."""
    if not foto_bytes:
        enviar(chat_id, "🎨 Sem foto do produto, então não gerei as artes desta vez.")
        return
    dados = {"nome": oferta["nome"], "por": oferta["por"], "de": oferta.get("de")}
    legenda = arte.legenda_instagram(dados, TELEGRAM_LINK)
    artes = {}
    for formato, rotulo in (("story", "📱 Story (1080×1920)"), ("post", "🖼️ Post do feed (1080×1350)")):
        artes[formato] = arte.gerar(dados, foto_bytes, formato, TELEGRAM_LINK)
        api("sendDocument", arquivos={"document": (f"ocacapreco_{formato}.png", artes[formato])},
            chat_id=chat_id, caption=rotulo)

    cfg_ig = CFG.get("instagram", {})
    if instagram.configurado() and (cfg_ig.get("feed") or cfg_ig.get("story")):
        linhas = ["📸 <b>Instagram</b>"]
        if cfg_ig.get("feed"):
            try:
                link = instagram.publicar(artes["post"], legenda=legenda)
                linhas.append("✅ Post no feed publicado" + (f": {link}" if link else ""))
            except Exception as e:
                linhas.append(f"❌ Feed: {html.escape(str(e))}")
        if cfg_ig.get("story"):
            try:
                instagram.publicar(artes["story"], story=True)
                linhas.append("✅ Story publicado (lembre de adicionar a figurinha de link pelo app, se quiser)")
            except Exception as e:
                linhas.append(f"❌ Story: {html.escape(str(e))}")
        if not cfg_ig.get("story"):
            linhas.append(
                "\n📱 <b>Story com link clicável</b> (20 segundos):\n"
                "1️⃣ Salve a imagem <b>Story</b> acima\n"
                "2️⃣ Instagram › novo story › escolha a imagem\n"
                "3️⃣ Figurinha <b>Link</b> › cole o link abaixo › texto: ENTRA NO CANAL 🔥\n\n"
                f"<code>https://{TELEGRAM_LINK}</code>")
        enviar(chat_id, "\n".join(linhas))
    else:
        enviar(chat_id, "📝 <b>Legenda para o Instagram</b> (toque para copiar):\n\n<code>"
               + html.escape(legenda) + "</code>")


def concluir_publicacao(chat_id, oferta, foto_publicar, foto_bytes):
    enviado = publicar(CANAL, montar_post(oferta), foto_publicar)
    usuario = enviado.get("chat", {}).get("username")
    enviar(chat_id, "✅ Publicado no canal!" + (f"\nhttps://t.me/{usuario}/{enviado['message_id']}" if usuario else ""))
    try:
        enviar_artes(chat_id, oferta, foto_bytes)
    except Exception as e:
        enviar(chat_id, f"🎨 Publiquei, mas não consegui gerar as artes: {html.escape(str(e))}")


# ================================================================ Busca de ofertas
def buscar(chat_id):
    if not ml.conectado():
        enviar(chat_id, "🔌 Para eu buscar ofertas, conecte sua conta do Mercado Livre: mande /conectar")
        return
    vistos = ler_json("vistos.json", {})
    agora = time.time()
    vistos = {k: v for k, v in vistos.items() if agora - v < 14 * 86400}
    sugestoes = ler_json("sugestoes.json", {})
    sugestoes = {k: v for k, v in sugestoes.items() if agora - v.get("quando", 0) < 14 * 86400}

    minimo = CFG.get("desconto_minimo", 20)
    por_cat = CFG.get("produtos_por_categoria", 15)
    candidatos, erros = [], []
    lidos, falhas, maior = 0, 0, 0
    for cat, nome_cat in CFG.get("categorias", {}).items():
        try:
            for id_, tipo in ml.mais_vendidos(cat, por_cat):
                if id_ in vistos and agora - vistos[id_] < 7 * 86400:
                    continue
                try:
                    d = ml.detalhes(id_, tipo)
                except ml.ErroML:
                    raise
                except Exception as e:
                    print("Produto ignorado", id_, e)
                    d = None
                if not d:
                    falhas += 1
                    continue
                lidos += 1
                maior = max(maior, d["desconto"])
                if d["desconto"] >= minimo:
                    d["categoria"] = nome_cat
                    candidatos.append(d)
        except ml.ErroML as e:
            erros.append(str(e))
            if "conect" in str(e).lower():
                break

    candidatos.sort(key=lambda d: d["desconto"], reverse=True)
    escolhidos = candidatos[: CFG.get("max_sugestoes_por_busca", 6)]

    for d in escolhidos:
        legenda = (
            f"🆕 <b>SUGESTÃO</b> · {html.escape(d['categoria'])}\n\n"
            f"<b>{html.escape(d['nome'])}</b>\n"
            f"<s>{reais(d['de'])}</s> → <b>{reais(d['por'])}</b>  ({d['desconto']}% OFF)\n\n"
            "1️⃣ Toque em <b>Abrir produto</b>\n"
            "2️⃣ <b>Compartilhar › Copiar link</b>\n"
            "3️⃣ <b>Responda esta mensagem</b> colando o link\n"
            "(não quer? é só ignorar)\n\n"
            f"🆔 {d['id']}"
        )
        teclado = {"inline_keyboard": [[{"text": "🔗 Abrir produto", "url": d["link_produto"]}]]} if d.get("link_produto") else None
        try:
            publicar_sugestao = api("sendPhoto", chat_id=chat_id, photo=d["foto"], caption=legenda,
                                    parse_mode="HTML", reply_markup=teclado) if d.get("foto") else None
        except RuntimeError:
            publicar_sugestao = None
        if not publicar_sugestao:
            enviar(chat_id, legenda, reply_markup=teclado)
        d["quando"] = agora
        sugestoes[d["id"]] = d
        vistos[d["id"]] = agora

    salvar_json("vistos.json", vistos)
    salvar_json("sugestoes.json", sugestoes)

    resumo = f"🔎 Busca concluída: {len(escolhidos)} sugest{'ão' if len(escolhidos) == 1 else 'ões'}"
    resumo += f"\n📊 Produtos lidos: {lidos} · sem dados: {falhas} · maior desconto: {maior}%"
    if not escolhidos and lidos:
        resumo += f"\nNenhum mais vendido novo com {minimo}% OFF ou mais agora. Tento de novo mais tarde."
    if not lidos:
        resumo += "\n⚠️ Não consegui ler nenhum produto. Mande /diagnostico para ver o motivo."
    if erros:
        resumo += "\n\n⚠️ " + "\n⚠️ ".join(html.escape(e) for e in erros[:3])
    enviar(chat_id, resumo)


def publicar_sugestao(chat_id, msg, id_):
    link, extras = separar_link(msg.get("text") or msg.get("caption") or "")
    if not link:
        enviar(chat_id, "❌ Para publicar, responda a sugestão colando o seu link de afiliado (meli.la/...).")
        return
    sugestoes = ler_json("sugestoes.json", {})
    d = sugestoes.get(id_)
    try:  # atualiza o preço na hora de publicar
        novo = ml.detalhes(id_, (d or {}).get("tipo", "PRODUCT"))
        if novo:
            d = {**(d or {}), **novo}
    except Exception as e:
        print("Não atualizei o preço:", e)
    if not d:
        enviar(chat_id, "❌ Não achei os dados dessa sugestão. Mande a oferta no jeito manual (/modelo).")
        return
    oferta = {"nome": d["nome"], "por": d["por"], "de": d.get("de"),
              "vantagens": [x.lstrip("-•✅* ").strip() for x in extras if x.strip()], "link": link}
    concluir_publicacao(chat_id, oferta, d.get("foto"), baixar(d["foto"]) if d.get("foto") else None)


# ================================================================ Mensagens
def tratar(msg, pedidos):
    chat_id = msg["chat"]["id"]
    de_quem = str(msg.get("from", {}).get("id", ""))
    texto = (msg.get("text") or msg.get("caption") or "").strip()

    if msg["chat"].get("type") != "private":
        return
    if not OWNER_ID:
        enviar(chat_id, f"Seu ID do Telegram é: <code>{de_quem}</code>\n\n"
                        "Coloque esse número no segredo OWNER_ID do GitHub. Até lá eu não publico nada.")
        return
    if de_quem != OWNER_ID:
        enviar(chat_id, "Este bot é privado. 🎯 Siga as ofertas em " + CANAL)
        return

    cmd = texto.lower().split()[0] if texto else ""
    redirect = CFG.get("redirect_uri", "")

    if cmd == "/start":
        enviar(chat_id, f"Olá! 🎯 Canal: {CANAL}\n\n" + html.escape(MODELO))
        return
    if cmd in ("/modelo", "/ajuda", "/help"):
        enviar(chat_id, html.escape(MODELO))
        return
    if cmd == "/conectar":
        try:
            link = ml.link_autorizacao(redirect)
        except ml.ErroML as e:
            enviar(chat_id, "❌ " + html.escape(str(e)))
            return
        enviar(chat_id,
               "🔌 <b>Conectar sua conta do Mercado Livre</b>\n\n"
               f"1️⃣ Abra: <a href=\"{html.escape(link, quote=True)}\">autorizar o O Caça Preço Bot</a>\n"
               "2️⃣ Clique em <b>Permitir</b>.\n"
               "3️⃣ Você vai cair numa página do GitHub. Copie o <b>endereço inteiro</b> da barra "
               "(ele tem <code>code=TG-...</code>) e mande aqui.\n"
               "4️⃣ Logo depois, rode o workflow no GitHub (Actions › Run workflow). "
               "O código vale só 10 minutos!")
        return
    if cmd == "/status":
        cats = "\n".join(f"• {n}" for n in CFG.get("categorias", {}).values())
        enviar(chat_id, f"🎯 Canal: {CANAL}\n"
                        f"🔌 Mercado Livre: {'conectado ✅' if ml.conectado() else 'não conectado ❌ (/conectar)'}\n"
                        f"📉 Desconto mínimo: {CFG.get('desconto_minimo', 20)}%\n"
                        f"📂 Categorias:\n{cats}")
        return
    if cmd == "/diagnostico":
        cat = next(iter(CFG.get("categorias", {"MLB1246": ""})))
        enviar(chat_id, "🩺 <b>Diagnóstico</b>\n\n" + html.escape(ml.diagnostico(cat)))
        return
    if cmd == "/instagram":
        if not instagram.configurado():
            enviar(chat_id, "📸 Instagram ainda não configurado: falta o segredo IG_TOKEN no GitHub.")
            return
        try:
            c = instagram.conta()
            cfg_ig = CFG.get("instagram", {})
            enviar(chat_id, f"📸 Instagram conectado: @{html.escape(str(c.get('username')))} "
                            f"({html.escape(str(c.get('account_type')))})\n"
                            f"Feed automático: {'ligado ✅' if cfg_ig.get('feed') else 'desligado'}\n"
                            f"Story automático: {'ligado ✅' if cfg_ig.get('story') else 'desligado'}")
        except Exception as e:
            enviar(chat_id, "❌ " + html.escape(str(e)))
        return
    if cmd == "/buscar":
        pedidos["buscar"] = True
        enviar(chat_id, "🔎 Buscando ofertas agora…")
        return

    codigo = CODIGO_RE.search(texto)
    if codigo and ("code=" in texto or texto.startswith("TG-")):
        try:
            ml.trocar_codigo(codigo.group(1), redirect)
            enviar(chat_id, "✅ Conta do Mercado Livre conectada! Vou buscar as primeiras ofertas agora.")
            pedidos["buscar"] = True
        except ml.ErroML as e:
            enviar(chat_id, "❌ " + html.escape(str(e)))
        return

    resposta = msg.get("reply_to_message") or {}
    id_sug = ID_RE.search(resposta.get("caption") or resposta.get("text") or "")
    if id_sug:
        publicar_sugestao(chat_id, msg, id_sug.group(1))
        return

    so_teste = cmd.startswith("teste")
    if so_teste:
        texto = texto[5:].lstrip(" :-\n")
    oferta, erro = ler_oferta(texto)
    if erro:
        enviar(chat_id, "❌ " + html.escape(erro) + "\n\n" + html.escape(MODELO))
        return
    foto_id = msg["photo"][-1]["file_id"] if msg.get("photo") else None
    if so_teste:
        publicar(chat_id, montar_post(oferta), foto_id)
        enviar(chat_id, "👆 Prévia. Para publicar, mande de novo sem a palavra \"teste\".")
        return
    concluir_publicacao(chat_id, oferta, foto_id, foto_do_telegram(foto_id) if foto_id else None)


# ================================================================ Execução
def main():
    if not TOKEN:
        sys.exit("Falta o segredo TELEGRAM_TOKEN.")
    pedidos = {"buscar": MODO == "buscar"}
    atualizacoes = api("getUpdates", timeout=0, allowed_updates=["message"])
    print(f"Modo: {MODO} · {len(atualizacoes)} mensagem(ns) nova(s).")
    for upd in atualizacoes:
        msg = upd.get("message")
        if msg:
            try:
                tratar(msg, pedidos)
            except Exception as e:
                print("Erro:", e)
                try:
                    enviar(msg["chat"]["id"], f"❌ Algo deu errado: {html.escape(str(e))}")
                except Exception:
                    pass
        api("getUpdates", offset=upd["update_id"] + 1, timeout=0)

    if pedidos["buscar"] and OWNER_ID:
        try:
            buscar(OWNER_ID)
        except Exception as e:
            print("Erro na busca:", e)
            enviar(OWNER_ID, f"❌ Erro na busca de ofertas: {html.escape(str(e))}")


if __name__ == "__main__":
    main()
