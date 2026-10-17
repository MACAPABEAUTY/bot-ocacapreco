"""
Conexão com a API oficial do Mercado Livre.

- Conecta a sua conta uma vez (OAuth) e guarda o token CRIPTOGRAFADO em state/ml_token.enc.
  A chave de criptografia vem do segredo ML_CLIENT_SECRET, então o arquivo é ilegível
  para quem visitar o repositório.
- Busca os mais vendidos de cada categoria e calcula o desconto de cada produto.
"""

import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from cryptography.fernet import Fernet, InvalidToken

API = "https://api.mercadolibre.com"
AUTH = "https://auth.mercadolivre.com.br/authorization"
CLIENT_ID = os.environ.get("ML_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("ML_CLIENT_SECRET", "").strip()
STATE_DIR = os.environ.get("STATE_DIR", "state")
TOKEN_FILE = os.path.join(STATE_DIR, "ml_token.enc")


class ErroML(Exception):
    pass


# ---------------------------------------------------------------- HTTP
def _http(metodo, url, dados=None, token=None):
    cab = {"Accept": "application/json", "User-Agent": "ocacapreco-bot/2.0"}
    corpo = None
    if dados is not None:
        corpo = urllib.parse.urlencode(dados).encode()
        cab["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        cab["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=corpo, headers=cab, method=metodo)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        texto = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(texto)
        except ValueError:
            return e.code, {"message": texto[:200]}


# ---------------------------------------------------------------- Token guardado
def _fernet():
    if not CLIENT_SECRET:
        raise ErroML("Falta o segredo ML_CLIENT_SECRET no GitHub.")
    chave = base64.urlsafe_b64encode(hashlib.sha256(CLIENT_SECRET.encode()).digest())
    return Fernet(chave)


def _ler_token():
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "rb") as f:
            return json.loads(_fernet().decrypt(f.read()))
    except (InvalidToken, ValueError):
        return None


def _salvar_token(dados):
    os.makedirs(STATE_DIR, exist_ok=True)
    dados = dict(dados)
    dados["expira_em"] = time.time() + int(dados.get("expires_in", 21600)) - 300
    guardar = {k: dados.get(k) for k in ("access_token", "refresh_token", "expira_em", "user_id")}
    with open(TOKEN_FILE, "wb") as f:
        f.write(_fernet().encrypt(json.dumps(guardar).encode()))


def conectado():
    return _ler_token() is not None


def link_autorizacao(redirect_uri):
    if not CLIENT_ID:
        raise ErroML("Falta o segredo ML_CLIENT_ID no GitHub.")
    q = urllib.parse.urlencode({"response_type": "code", "client_id": CLIENT_ID, "redirect_uri": redirect_uri})
    return f"{AUTH}?{q}"


def trocar_codigo(codigo, redirect_uri):
    """Troca o código TG-... (que aparece no endereço depois de autorizar) pelo token."""
    st, resp = _http("POST", f"{API}/oauth/token", {
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": codigo,
        "redirect_uri": redirect_uri,
    })
    if st != 200 or "access_token" not in resp:
        raise ErroML(f"Não consegui conectar ({st}): {resp.get('message') or resp.get('error')}. "
                     "O código vale só 10 minutos; gere outro com /conectar.")
    _salvar_token(resp)
    return resp.get("user_id")


def token():
    t = _ler_token()
    if not t:
        raise ErroML("Conta do Mercado Livre não conectada. Mande /conectar.")
    if time.time() < t.get("expira_em", 0):
        return t["access_token"]
    st, resp = _http("POST", f"{API}/oauth/token", {
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "refresh_token": t["refresh_token"],
    })
    if st != 200 or "access_token" not in resp:
        raise ErroML(f"A conexão com o Mercado Livre expirou ({st}). Mande /conectar de novo.")
    _salvar_token(resp)
    return resp["access_token"]


def get(caminho):
    st, resp = _http("GET", API + caminho, token=token())
    return st, resp


# ---------------------------------------------------------------- Produtos
def _foto(lista):
    for p in lista or []:
        url = p.get("secure_url") or p.get("url")
        if url:
            return url.replace("http://", "https://").replace("-I.jpg", "-O.jpg")
    return None


def _preco_item(item_id):
    """Retorna (preço atual, preço antigo) usando o preço promocional oficial."""
    st, sp = get(f"/items/{item_id}/sale_price?context=channel_marketplace")
    if st == 200 and isinstance(sp, dict) and sp.get("amount"):
        por = float(sp["amount"])
        de = sp.get("regular_amount")
        return por, (float(de) if de else None)
    st, it = get(f"/items/{item_id}")
    if st == 200 and it.get("price"):
        return float(it["price"]), (float(it["original_price"]) if it.get("original_price") else None)
    return None, None


def detalhes(id_, tipo="ITEM"):
    """Junta nome, foto, link e preços de um produto (catálogo) ou anúncio."""
    info = {"id": id_, "tipo": tipo}
    if tipo == "PRODUCT":
        st, p = get(f"/products/{id_}")
        if st != 200:
            return None
        info["nome"] = p.get("name")
        info["foto"] = _foto(p.get("pictures"))
        info["link_produto"] = p.get("permalink") or f"https://www.mercadolivre.com.br/p/{id_}"
        bbw = p.get("buy_box_winner") or {}
        item_id = bbw.get("item_id")
        if not item_id:
            return None
        info["item_id"] = item_id
        por, de = _preco_item(item_id)
        if por is None and bbw.get("price"):
            por, de = float(bbw["price"]), (float(bbw["original_price"]) if bbw.get("original_price") else None)
    else:
        st, it = get(f"/items/{id_}")
        if st != 200:
            return None
        info["nome"] = it.get("title")
        info["foto"] = _foto(it.get("pictures")) or it.get("thumbnail")
        info["link_produto"] = it.get("permalink")
        info["item_id"] = id_
        por, de = _preco_item(id_)
    if not info.get("nome") or por is None:
        return None
    info["por"] = por
    info["de"] = de if de and de > por else None
    info["desconto"] = round((1 - por / de) * 100) if info["de"] else 0
    return info


def mais_vendidos(categoria, limite=15):
    st, resp = get(f"/highlights/MLB/category/{categoria}")
    if st != 200:
        raise ErroML(f"Mais vendidos de {categoria}: erro {st} {resp.get('message', '') if isinstance(resp, dict) else ''}")
    return [(c["id"], c.get("type", "ITEM")) for c in (resp.get("content") or [])[:limite]]


def diagnostico(categoria):
    """Testa cada etapa e devolve um relatório em texto."""
    linhas = []
    try:
        token()
        linhas.append("✅ Token do Mercado Livre OK")
    except ErroML as e:
        return f"❌ {e}"
    st, me = get("/users/me")
    linhas.append(f"{'✅' if st == 200 else '❌'} Conta: {me.get('nickname', st) if isinstance(me, dict) else st}")
    st, hl = get(f"/highlights/MLB/category/{categoria}")
    n = len(hl.get("content") or []) if isinstance(hl, dict) else 0
    linhas.append(f"{'✅' if st == 200 else '❌'} Mais vendidos ({categoria}): {st}, {n} produtos")
    if st == 200 and n:
        c = hl["content"][0]
        d = detalhes(c["id"], c.get("type", "ITEM"))
        if d:
            linhas.append(f"✅ Produto: {d['nome'][:50]} · R$ {d['por']:.2f} · {d['desconto']}% OFF")
        else:
            linhas.append(f"❌ Não consegui ler o produto {c['id']} ({c.get('type')})")
    return "\n".join(linhas)
