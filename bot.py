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
import video  # noqa: E402

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
    "Comandos: /rodada /buscar /canalig /video /status /conectar /diagnostico /instagram"
)
MARCA_IG = "📲 CANAL DO INSTAGRAM"

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
    cfg_com = CFG.get("comente", {})
    palavra = cfg_com.get("palavra", "QUERO") if cfg_com.get("ativo") else None
    legenda = arte.legenda_instagram(dados, TELEGRAM_LINK, palavra)
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
                media_id, link = instagram.publicar(artes["post"], legenda=legenda)
                linhas.append("✅ Post no feed publicado" + (f": {link}" if link else ""))
                posts = ler_json("posts_ig.json", {})
                posts[media_id] = {"nome": oferta["nome"], "link": oferta["link"], "quando": time.time()}
                posts = {k: v for k, v in posts.items() if time.time() - v.get("quando", 0) < 8 * 86400}
                salvar_json("posts_ig.json", posts)
            except Exception as e:
                linhas.append(f"❌ Feed: {html.escape(str(e))}")
        if cfg_ig.get("story"):
            try:
                instagram.publicar(artes["story"], story=True)  # retorna (id, link)
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


# ================================================================ Modo automático (10 por hora)
def hora_local():
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=-3)))


def proximas_categorias(qtd):
    """Rodízio entre categorias e subcategorias, para achar produtos novos sempre."""
    rot = ler_json("rotacao.json", {})
    fila = rot.get("fila") or list(CFG.get("categorias", {}).keys())
    expandidas = set(rot.get("expandidas", []))
    pos = rot.get("pos", 0) % max(1, len(fila))
    escolhidas = []
    for _ in range(min(qtd, len(fila))):
        cat = fila[pos]
        escolhidas.append(cat)
        if cat not in expandidas and len(fila) < 800:
            try:
                for filho in ml.subcategorias(cat):
                    if filho not in fila:
                        fila.append(filho)
            except Exception as e:
                print("Subcategorias falharam:", cat, e)
            expandidas.add(cat)
        pos = (pos + 1) % len(fila)
    salvar_json("rotacao.json", {"fila": fila, "pos": pos, "expandidas": sorted(expandidas)})
    return escolhidas


def rodada_automatica():
    cfg = CFG.get("auto", {})
    afil = CFG.get("afiliado", {})
    if not cfg.get("ativo"):
        return
    agora_l = hora_local()
    ini, fim = cfg.get("horario", [8, 23])
    if not (ini <= agora_l.hour <= fim):
        print(f"Fora do horário ({agora_l:%H:%M}), sem publicações automáticas.")
        return
    if not (afil.get("matt_word") and afil.get("matt_tool")):
        enviar(OWNER_ID, "⚠️ Modo automático: falta o código de afiliado no config.json.")
        return
    if not ml.conectado():
        enviar(OWNER_ID, "⚠️ Modo automático parado: conecte o Mercado Livre com /conectar.")
        return
    try:
        ml.token()  # confere a conexão antes de começar
    except ml.ErroML as e:
        aviso = ler_json("aviso_conexao.json", {})
        if time.time() - aviso.get("quando", 0) > 3 * 3600:
            enviar(OWNER_ID, "⚠️ <b>Modo automático parado</b>\n" + html.escape(str(e)))
            salvar_json("aviso_conexao.json", {"quando": time.time()})
        return

    publicados = ler_json("publicados.json", {})
    marca = agora_l.strftime("%Y-%m-%d %H")
    if ler_json("ultima_rodada.json", {}).get("marca") == marca:
        print("Rodada desta hora já foi feita.")
        return

    quantos = cfg.get("por_hora", 10)
    minimo = cfg.get("desconto_minimo", 15)
    candidatos, vistos_rodada = [], set()
    for cat in proximas_categorias(cfg.get("categorias_por_rodada", 8)):
        try:
            lista = ml.mais_vendidos(cat, 20)
        except ml.ErroML as e:
            print("Categoria pulada:", cat, e)
            continue
        for id_, tipo in lista:
            if id_ in publicados or id_ in vistos_rodada:
                continue
            vistos_rodada.add(id_)
            try:
                d = ml.detalhes(id_, tipo)
            except Exception as e:
                print("Produto ignorado", id_, e)
                continue
            if d and d["desconto"] >= minimo and d.get("link_produto") and d.get("foto"):
                candidatos.append(d)
        if len(candidatos) >= quantos * 3:
            break

    candidatos.sort(key=lambda d: d["desconto"], reverse=True)
    escolhidos = candidatos[:quantos]
    ig_horas = cfg.get("instagram_horas", [])
    ig_dia = ler_json("instagram_dia.json", {})
    hoje = agora_l.strftime("%Y-%m-%d")
    post_ig = agora_l.hour in ig_horas and str(agora_l.hour) not in ig_dia.get(hoje, [])

    feitos = 0
    for i, d in enumerate(escolhidos):
        link = ml.link_afiliado(d["link_produto"], afil["matt_word"], afil["matt_tool"])
        oferta = {"nome": d["nome"], "por": d["por"], "de": d.get("de"), "vantagens": [], "link": link}
        try:
            if i == 0 and post_ig:  # o melhor da rodada também vai para o Instagram
                concluir_publicacao(OWNER_ID, oferta, d["foto"], baixar(d["foto"]))
                ig_dia = {hoje: ig_dia.get(hoje, []) + [str(agora_l.hour)]}
                salvar_json("instagram_dia.json", ig_dia)
            else:
                publicar(CANAL, montar_post(oferta), d["foto"])
            publicados[d["id"]] = int(time.time())
            feitos += 1
            salvar_json("publicados.json", publicados)
        except Exception as e:
            print("Falha ao publicar", d["id"], e)
        if i < len(escolhidos) - 1:
            time.sleep(cfg.get("intervalo_segundos", 20))

    salvar_json("ultima_rodada.json", {"marca": marca})
    if escolhidos:  # guarda os melhores da rodada para o pacote do canal do Instagram
        salvar_json("destaques.json", {"quando": time.time(), "itens": escolhidos[:10]})
    try:
        pacote_canal_ig_agendado(agora_l)
    except Exception as e:
        print("Pacote do canal IG falhou:", e)
    try:
        videos_agendados(agora_l)
    except Exception as e:
        print("Vídeo falhou:", e)
    meta = cfg.get("meta", 5000)
    if cfg.get("avisar_cada_rodada", True):
        enviar(OWNER_ID, f"🤖 Rodada das {agora_l:%H:%M}: {feitos} oferta(s) publicada(s) no canal"
                         + (" (1 também no Instagram)" if post_ig and feitos else "")
                         + f"\n📦 Total: {len(publicados)} / {meta}"
                         + ("" if feitos else f"\nNenhum produto novo com {minimo}% OFF nas categorias desta hora."))


# ================================================================ Canal de transmissão do Instagram
def texto_canal_ig(d, link):
    linhas = [f"🔥 {d['nome']}", ""]
    if d.get("de") and d["de"] > d["por"]:
        desconto = round((1 - d["por"] / d["de"]) * 100)
        linhas.append(f"De {reais(d['de'])} por {reais(d['por'])} ({desconto}% OFF)")
    else:
        linhas.append(f"Por {reais(d['por'])}")
    linhas += ["", f"👉 {link}", "", RODAPE]
    return "\n".join(linhas)


def enviar_pacote_canal_ig(chat_id, itens):
    """Manda para o dono as melhores ofertas, prontas para o canal de transmissão do Instagram."""
    if not itens:
        enviar(chat_id, "📲 Ainda não tenho ofertas recentes para o canal do Instagram. Mande /rodada e depois /canalig.")
        return 0
    guardados = ler_json("pacote_ig.json", {})
    agora = time.time()
    guardados = {k: v for k, v in guardados.items() if agora - v.get("quando", 0) < 7 * 86400}
    enviar(chat_id, f"{MARCA_IG} · <b>{len(itens)} oferta(s) de hoje</b>\n\n"
                    "Para cada uma:\n"
                    "1️⃣ <b>Abrir produto</b> › <b>Compartilhar</b> › copiar o link (meli.la)\n"
                    "2️⃣ <b>Responda a mensagem</b> da oferta colando o link\n"
                    "3️⃣ Eu devolvo a foto + o texto pronto. Salve a foto, toque no texto para copiar "
                    "e mande no canal do Instagram 📲")
    for d in itens:
        legenda = (f"{MARCA_IG}\n\n<b>{html.escape(d['nome'])}</b>\n"
                   + (f"<s>{reais(d['de'])}</s> → " if d.get("de") else "")
                   + f"<b>{reais(d['por'])}</b>"
                   + (f"  ({d['desconto']}% OFF)" if d.get("desconto") else "")
                   + "\n\n↩️ Responda esta mensagem com o link meli.la\n\n"
                   f"🆔 {d['id']}")
        teclado = {"inline_keyboard": [[{"text": "🔗 Abrir produto", "url": d["link_produto"]}]]} if d.get("link_produto") else None
        try:
            if not d.get("foto"):
                raise RuntimeError("sem foto")
            api("sendPhoto", chat_id=chat_id, photo=d["foto"], caption=legenda, parse_mode="HTML", reply_markup=teclado)
        except RuntimeError:
            enviar(chat_id, legenda, reply_markup=teclado)
        guardados[d["id"]] = {k: d.get(k) for k in ("id", "nome", "por", "de", "foto", "link_produto", "tipo")}
        guardados[d["id"]]["quando"] = agora
    salvar_json("pacote_ig.json", guardados)
    return len(itens)


def melhores_para_canal_ig(qtd):
    dados = ler_json("destaques.json", {})
    if time.time() - dados.get("quando", 0) > 2 * 86400:
        return []
    ja = ler_json("pacote_ig.json", {})
    itens = [d for d in dados.get("itens", []) if d.get("id") not in ja]
    itens.sort(key=lambda d: d.get("desconto", 0), reverse=True)
    return itens[:qtd]


def pacote_canal_ig_agendado(agora_l):
    cfg = CFG.get("canal_ig", {})
    if not cfg.get("ativo") or not OWNER_ID:
        return
    horas = sorted(cfg.get("horas", [12, 19]))
    hoje = agora_l.strftime("%Y-%m-%d")
    feitos = ler_json("canal_ig_dia.json", {}).get(hoje, [])
    vencidas = [h for h in horas if h <= agora_l.hour]
    if not vencidas or vencidas[-1] in feitos:  # se o GitHub pular um horário, manda na rodada seguinte
        return
    if enviar_pacote_canal_ig(OWNER_ID, melhores_para_canal_ig(cfg.get("ofertas", 3))):
        salvar_json("canal_ig_dia.json", {hoje: sorted(set(feitos + vencidas))})


def responder_pacote_ig(chat_id, msg, id_):
    link, _ = separar_link(msg.get("text") or msg.get("caption") or "")
    if not link:
        enviar(chat_id, "❌ Responda a oferta colando o link de afiliado (meli.la/...).")
        return
    d = ler_json("pacote_ig.json", {}).get(id_)
    if not d:
        enviar(chat_id, "❌ Não achei os dados dessa oferta (ela tem mais de 7 dias). Mande /canalig para receber novas.")
        return
    try:  # confere o preço de agora
        novo = ml.detalhes(id_, d.get("tipo") or "PRODUCT")
        if novo:
            d = {**d, **{k: novo.get(k) for k in ("nome", "por", "de") if novo.get(k)}}
    except Exception as e:
        print("Não atualizei o preço:", e)
    aviso = "" if re.search(r"meli\.la|mercadoli[vb]re", link, re.I) else \
        "\n⚠️ Esse link não parece ser do Mercado Livre. Confira antes de mandar."
    texto = texto_canal_ig(d, link)
    if d.get("foto"):
        try:
            api("sendPhoto", chat_id=chat_id, photo=d["foto"], caption="📲 Foto para o canal (segure › Salvar)")
        except RuntimeError as e:
            print("Foto falhou:", e)
    enviar(chat_id, "✅ <b>Pronto para o canal do Instagram</b> — toque no texto para copiar:\n\n<code>"
           + html.escape(texto) + "</code>" + aviso)


# ================================================================ Vídeos para TikTok / Reels
def enviar_videos(chat_id, qtd=1):
    dados = ler_json("destaques.json", {})
    usados = ler_json("videos.json", {})
    agora = time.time()
    usados = {k: v for k, v in usados.items() if agora - v < 30 * 86400}
    itens = [d for d in dados.get("itens", []) if d.get("id") not in usados and d.get("foto")]
    itens.sort(key=lambda d: d.get("desconto", 0), reverse=True)
    if not itens:
        enviar(chat_id, "🎬 Ainda não tenho ofertas novas para vídeo. Mande /rodada e depois /video.")
        return 0
    feitos = 0
    for d in itens[:qtd]:
        oferta = {"nome": d["nome"], "por": d["por"], "de": d.get("de"), "desconto": d.get("desconto")}
        try:
            mp4 = video.gerar(oferta, baixar(d["foto"]), telegram=TELEGRAM_LINK)
        except Exception as e:
            print("Vídeo falhou", d.get("id"), e)
            continue
        legenda = video.legenda_tiktok(oferta)
        api("sendVideo", arquivos={"video": ("ocacapreco_video.mp4", mp4)}, chat_id=chat_id,
            supports_streaming="true", width=1080, height=1920,
            caption=("🎬 <b>Vídeo para TikTok / Reels</b>\n"
                     "Salve o vídeo, poste e escolha um <b>som em alta</b> no app.\n\n"
                     "Legenda (toque para copiar):\n<code>" + html.escape(legenda) + "</code>")[:1024],
            parse_mode="HTML")
        usados[d["id"]] = agora
        feitos += 1
    salvar_json("videos.json", usados)
    return feitos


def videos_agendados(agora_l):
    cfg = CFG.get("video", {})
    if not cfg.get("ativo") or not OWNER_ID:
        return
    horas = sorted(cfg.get("horas", [11, 15, 20]))
    hoje = agora_l.strftime("%Y-%m-%d")
    feitos = ler_json("video_dia.json", {}).get(hoje, [])
    vencidas = [h for h in horas if h <= agora_l.hour]
    if not vencidas or vencidas[-1] in feitos:
        return
    if enviar_videos(OWNER_ID, cfg.get("por_vez", 1)):
        salvar_json("video_dia.json", {hoje: sorted(set(feitos + vencidas))})


# ================================================================ Comente QUERO
def verificar_comentarios(cfg_com):
    posts = ler_json("posts_ig.json", {})
    if not posts:
        return
    respondidos = ler_json("respondidos_ig.json", {})
    agora = time.time()
    respondidos = {k: v for k, v in respondidos.items() if agora - v < 10 * 86400}
    enviados, erros = instagram.processar_comentarios(
        posts, respondidos,
        palavra=cfg_com.get("palavra", "QUERO"),
        msg_direct=cfg_com.get("direct", "Oi! 🎯 Aqui está o link de {nome}:\n{link}\n\n🔥 Mais ofertas todo dia no canal: {canal}"),
        msg_publica=cfg_com.get("publico", ""),
        canal_link=f"https://{TELEGRAM_LINK}",
    )
    salvar_json("respondidos_ig.json", respondidos)
    if enviados:
        enviar(OWNER_ID, f"💬 Mandei o link no Direct para {len(enviados)} pessoa(s): "
                         + ", ".join("@" + html.escape(u) for u in enviados[:10]))
    if erros:
        avisos = ler_json("avisos_ig.json", {})
        novos = [e for e in dict.fromkeys(erros) if agora - avisos.get(e, 0) > 86400]
        if novos:
            enviar(OWNER_ID, "⚠️ <b>Comente QUERO</b>\n" + "\n".join(html.escape(e) for e in novos[:3]))
            for e in novos:
                avisos[e] = agora
            salvar_json("avisos_ig.json", avisos)


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
                        f"🤖 Modo automático: {'ligado ✅' if CFG.get('auto', {}).get('ativo') else 'desligado'} "
                        f"({CFG.get('auto', {}).get('por_hora', 10)}/hora, "
                        f"{CFG.get('auto', {}).get('horario', [8, 23])[0]}h–{CFG.get('auto', {}).get('horario', [8, 23])[1]}h)\n"
                        f"📦 Publicados: {len(ler_json('publicados.json', {}))} / {CFG.get('auto', {}).get('meta', 5000)}\n"
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
                            f"Story automático: {'ligado ✅' if cfg_ig.get('story') else 'desligado'}\n"
                            f"Comente {html.escape(CFG.get('comente', {}).get('palavra', 'QUERO'))} → Direct: "
                            f"{'ligado ✅' if CFG.get('comente', {}).get('ativo') else 'desligado'} "
                            f"({len(ler_json('posts_ig.json', {}))} post(s) sendo vigiados)")
        except Exception as e:
            enviar(chat_id, "❌ " + html.escape(str(e)))
        return
    if cmd == "/rodada":
        pedidos["auto"] = True
        salvar_json("ultima_rodada.json", {})
        enviar(chat_id, "🤖 Rodando o modo automático agora…")
        return
    if cmd == "/buscar":
        pedidos["buscar"] = True
        enviar(chat_id, "🔎 Buscando ofertas agora…")
        return
    if cmd == "/video":
        enviar(chat_id, "🎬 Gerando o vídeo… (leva uns 30 segundos)")
        enviar_videos(chat_id, 1)
        return
    if cmd == "/canalig":
        enviar_pacote_canal_ig(chat_id, melhores_para_canal_ig(CFG.get("canal_ig", {}).get("ofertas", 3)))
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
    texto_resp = resposta.get("caption") or resposta.get("text") or ""
    id_sug = ID_RE.search(texto_resp)
    if id_sug and MARCA_IG in texto_resp:
        responder_pacote_ig(chat_id, msg, id_sug.group(1))
        return
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
    pedidos = {"buscar": MODO == "buscar", "auto": False}
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

    cfg_com = CFG.get("comente", {})
    if cfg_com.get("ativo") and OWNER_ID and instagram.configurado():
        try:
            verificar_comentarios(cfg_com)
        except Exception as e:
            print("Erro nos comentários:", e)

    if (MODO == "auto" or pedidos.get("auto")) and OWNER_ID:
        try:
            rodada_automatica()
        except Exception as e:
            print("Erro no modo automático:", e)
            enviar(OWNER_ID, f"❌ Erro no modo automático: {html.escape(str(e))}")

    if pedidos["buscar"] and OWNER_ID:
        try:
            buscar(OWNER_ID)
        except Exception as e:
            print("Erro na busca:", e)
            enviar(OWNER_ID, f"❌ Erro na busca de ofertas: {html.escape(str(e))}")


if __name__ == "__main__":
    main()
