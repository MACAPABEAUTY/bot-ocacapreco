"""
Publicação automática no Instagram (API oficial da Meta, "Instagram API with Instagram Login").

Como funciona:
1. A arte (JPEG) é enviada para a pasta midia/ do próprio repositório pelo GitHub,
   porque o Instagram só aceita imagens que estejam num endereço público.
2. O bot cria o post (feed) ou o story na API do Instagram e publica.
3. Depois apaga a imagem do repositório.

O token do Instagram vale 60 dias; o bot renova sozinho e guarda a versão
renovada CRIPTOGRAFADA em state/ig_token.enc.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import ml  # reaproveita a criptografia (_fernet)

GRAPH = "https://graph.instagram.com"
IG_TOKEN_SEGREDO = os.environ.get("IG_TOKEN", "").strip()
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GH_REPO = os.environ.get("GITHUB_REPOSITORY", "").strip()
GH_BRANCH = os.environ.get("GITHUB_REF_NAME", "main").strip() or "main"


class ErroIG(Exception):
    pass


def _http(metodo, url, dados=None, cab=None, corpo_json=None):
    cab = dict(cab or {})
    corpo = None
    if corpo_json is not None:
        corpo = json.dumps(corpo_json).encode()
        cab["Content-Type"] = "application/json"
    elif dados is not None:
        corpo = urllib.parse.urlencode(dados).encode()
    req = urllib.request.Request(url, data=corpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, {"message": texto[:200]}


def _erro(resp):
    if isinstance(resp, dict):
        e = resp.get("error")
        if isinstance(e, dict):
            return e.get("message") or str(e)
        return resp.get("message") or str(resp)
    return str(resp)


# ---------------------------------------------------------------- Token
def _arquivo():
    return os.path.join(ml.STATE_DIR, "ig_token.enc")


def _ler():
    try:
        with open(_arquivo(), "rb") as f:
            return json.loads(ml._fernet().decrypt(f.read()))
    except Exception:
        return None


def _salvar(dados):
    os.makedirs(ml.STATE_DIR, exist_ok=True)
    with open(_arquivo(), "wb") as f:
        f.write(ml._fernet().encrypt(json.dumps(dados).encode()))


def configurado():
    return bool(IG_TOKEN_SEGREDO or _ler())


def token():
    salvo = _ler()
    # se você trocar o segredo IG_TOKEN no GitHub, o novo passa a valer
    if IG_TOKEN_SEGREDO and (not salvo or salvo.get("origem") != IG_TOKEN_SEGREDO[-12:]):
        salvo = {"token": IG_TOKEN_SEGREDO, "renovado_em": 0, "origem": IG_TOKEN_SEGREDO[-12:]}
        _salvar(salvo)
    if not salvo:
        raise ErroIG("Instagram não configurado: falta o segredo IG_TOKEN no GitHub.")
    if time.time() - salvo.get("renovado_em", 0) > 3 * 86400:  # renova a cada 3 dias
        st, r = _http("GET", f"{GRAPH}/refresh_access_token?" + urllib.parse.urlencode(
            {"grant_type": "ig_refresh_token", "access_token": salvo["token"]}))
        if st == 200 and r.get("access_token"):
            salvo["token"] = r["access_token"]
            salvo["renovado_em"] = time.time()
            _salvar(salvo)
        elif st in (400, 401) and "expired" in _erro(r).lower():
            raise ErroIG("O token do Instagram expirou. Gere outro no painel da Meta e atualize o segredo IG_TOKEN.")
    return salvo["token"]


def conta():
    st, r = _http("GET", f"{GRAPH}/me?" + urllib.parse.urlencode(
        {"fields": "user_id,username,account_type", "access_token": token()}))
    if st != 200:
        raise ErroIG(f"Não consegui ler a conta do Instagram ({st}): {_erro(r)}")
    return r


# ---------------------------------------------------------------- Imagem pública (GitHub)
def _subir_imagem(jpeg, nome):
    if not (GH_TOKEN and GH_REPO):
        raise ErroIG("Falta GITHUB_TOKEN no workflow (veja o bot.yml novo).")
    caminho = f"midia/{nome}"
    st, r = _http("PUT", f"https://api.github.com/repos/{GH_REPO}/contents/{caminho}",
                  cab={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
                       "User-Agent": "ocacapreco-bot"},
                  corpo_json={"message": f"Imagem temporária {nome}", "branch": GH_BRANCH,
                              "content": base64.b64encode(jpeg).decode()})
    if st not in (200, 201):
        raise ErroIG(f"Não consegui hospedar a imagem ({st}): {_erro(r)}")
    sha = r["content"]["sha"]
    url = f"https://raw.githubusercontent.com/{GH_REPO}/{GH_BRANCH}/{caminho}"
    return url, caminho, sha


def _apagar_imagem(caminho, sha):
    _http("DELETE", f"https://api.github.com/repos/{GH_REPO}/contents/{caminho}",
          cab={"Authorization": f"Bearer {GH_TOKEN}", "Accept": "application/vnd.github+json",
               "User-Agent": "ocacapreco-bot"},
          corpo_json={"message": f"Remove imagem temporária {caminho}", "branch": GH_BRANCH, "sha": sha})


def _para_jpeg(png):
    from io import BytesIO
    from PIL import Image
    img = Image.open(BytesIO(png)).convert("RGB")
    saida = BytesIO()
    img.save(saida, "JPEG", quality=92, optimize=True)
    return saida.getvalue()


# ---------------------------------------------------------------- Publicar
def publicar(png, legenda=None, story=False):
    """Publica uma imagem no feed (com legenda) ou no story.
    Retorna (id do post, link do post)."""
    tk = token()
    ig_id = conta().get("user_id")
    nome = f"{int(time.time())}_{'story' if story else 'feed'}.jpg"
    url, caminho, sha = _subir_imagem(_para_jpeg(png), nome)
    try:
        time.sleep(3)  # dá tempo do endereço público ficar disponível
        params = {"image_url": url, "access_token": tk}
        if story:
            params["media_type"] = "STORIES"
        elif legenda:
            params["caption"] = legenda[:2200]
        st, r = _http("POST", f"{GRAPH}/{ig_id}/media", params)
        if st != 200 or not r.get("id"):
            raise ErroIG(f"Instagram recusou a imagem ({st}): {_erro(r)}")
        container = r["id"]
        for _ in range(20):  # espera o Instagram processar (até ~1 min)
            st, s = _http("GET", f"{GRAPH}/{container}?" + urllib.parse.urlencode(
                {"fields": "status_code", "access_token": tk}))
            codigo = (s or {}).get("status_code")
            if codigo == "FINISHED":
                break
            if codigo in ("ERROR", "EXPIRED"):
                raise ErroIG(f"Instagram não conseguiu processar a imagem ({codigo}).")
            time.sleep(3)
        st, r = _http("POST", f"{GRAPH}/{ig_id}/media_publish", {"creation_id": container, "access_token": tk})
        if st != 200 or not r.get("id"):
            raise ErroIG(f"Falha ao publicar no Instagram ({st}): {_erro(r)}")
        media_id = r["id"]
        st, p = _http("GET", f"{GRAPH}/{media_id}?" + urllib.parse.urlencode({"fields": "permalink", "access_token": tk}))
        return media_id, ((p or {}).get("permalink") if st == 200 else None)
    finally:
        try:
            _apagar_imagem(caminho, sha)
        except Exception as e:
            print("Não apaguei a imagem temporária:", e)


# ---------------------------------------------------------------- Comente QUERO
def _normalizar(texto):
    import unicodedata
    t = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in t if unicodedata.category(c) != "Mn").upper()


def comentarios(media_id):
    tk = token()
    st, r = _http("GET", f"{GRAPH}/{media_id}/comments?" + urllib.parse.urlencode(
        {"fields": "id,text,username,timestamp", "limit": 50, "access_token": tk}))
    if st != 200:
        raise ErroIG(f"Não consegui ler os comentários ({st}): {_erro(r)}")
    return (r or {}).get("data") or []


def responder_direct(comment_id, texto):
    """Resposta privada: manda uma mensagem no Direct de quem comentou (1 por comentário, até 7 dias)."""
    tk = token()
    ig_id = conta().get("user_id")
    st, r = _http("POST", f"{GRAPH}/{ig_id}/messages?" + urllib.parse.urlencode({"access_token": tk}),
                  corpo_json={"recipient": {"comment_id": comment_id}, "message": {"text": texto}})
    if st != 200:
        raise ErroIG(f"Direct não enviado ({st}): {_erro(r)}")


def responder_publico(comment_id, texto):
    tk = token()
    st, r = _http("POST", f"{GRAPH}/{comment_id}/replies", {"message": texto, "access_token": tk})
    if st != 200:
        raise ErroIG(f"Resposta no comentário não enviada ({st}): {_erro(r)}")


def processar_comentarios(posts, respondidos, palavra, msg_direct, msg_publica, canal_link):
    """posts = {media_id: {nome, link, quando}}; respondidos = {comment_id: quando}.
    Retorna (enviados, erros)."""
    agora = time.time()
    enviados, erros = [], []
    alvo = _normalizar(palavra)
    for media_id, post in posts.items():
        if agora - post.get("quando", 0) > 7 * 86400:  # o Instagram só permite responder até 7 dias
            continue
        try:
            lista = comentarios(media_id)
        except ErroIG as e:
            erros.append(str(e))
            continue
        for c in lista:
            cid = c.get("id")
            if not cid or cid in respondidos:
                continue
            if alvo not in _normalizar(c.get("text")):
                continue
            texto = msg_direct.format(nome=post.get("nome", "a oferta"), link=post.get("link", canal_link),
                                      canal=canal_link, usuario=c.get("username") or "")
            try:
                responder_direct(cid, texto)
                respondidos[cid] = agora
                enviados.append(c.get("username") or "alguém")
            except ErroIG as e:
                erros.append(str(e))
                respondidos[cid] = agora  # não tenta de novo a cada execução
                continue
            if msg_publica:
                try:
                    responder_publico(cid, msg_publica.format(usuario=c.get("username") or ""))
                except ErroIG as e:
                    print("Resposta pública falhou:", e)
    return enviados, erros
