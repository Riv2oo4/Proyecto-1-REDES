import os, json, unicodedata
from typing import Dict, List
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="mcp-hello-remote", stateless_http=True)

MORSE_TABLE: Dict[str, str] = {
    "A": ".-","B": "-...","C": "-.-.","D": "-..","E": ".",
    "F": "..-.","G": "--.","H": "....","I": "..","J": ".---",
    "K": "-.-","L": ".-..","M": "--","N": "-.","O": "---",
    "P": ".--.","Q": "--.-","R": ".-.","S": "...","T": "-",
    "U": "..-","V": "...-","W": ".--","X": "-..-","Y": "-.--",
    "Z": "--..","0": "-----","1": ".----","2": "..---","3": "...--",
    "4": "....-","5": ".....","6": "-....","7": "--...","8": "---..","9": "----."
}
REV_MORSE = {v: k for k, v in MORSE_TABLE.items()}

def _strip_accents(s: str) -> str:
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))

def _encode_morse(text: str) -> str:
    cleaned = _strip_accents(text).upper()
    words = cleaned.split()
    return " / ".join(" ".join(MORSE_TABLE.get(ch, "?") for ch in w) for w in words) if words else ""

def _decode_morse(code: str) -> str:
    if not code.strip(): return ""
    norm = code.replace("|", "/").strip()
    words = [w.strip() for w in norm.split("/") if w.strip()]
    return " ".join("".join(REV_MORSE.get(tok, "?") for tok in w.split()) for w in words)

@mcp.tool()
def echo(texto: str) -> str:
    return f"echo: {texto}"

@mcp.tool()
def morse(texto: str) -> str:
    return _encode_morse(texto)

@mcp.tool()
def demorse(codigo: str) -> str:
    return _decode_morse(codigo)

def _health_payload():
    return {
        "ok": True,
        "kind": "mcp-streamable-http",
        "mount": "/mcp",
        "tools": ["echo(texto)", "morse(texto)", "demorse(codigo)"],
    }

# --- ASGI apps ---
mcp_asgi = mcp.streamable_http_app()   # EXPONE /mcp internamente. NO reescribas paths.

async def _cors_send(send, ev):
    if ev["type"] == "http.response.start":
        headers = ev.setdefault("headers", [])
        headers += [
            (b"access-control-allow-origin", b"*"),
            (b"access-control-allow-headers", b"*"),
            (b"access-control-allow-methods", b"GET,POST,OPTIONS"),
            # ¡Clave para el Inspector!
            (b"access-control-expose-headers", b"Mcp-Session-Id"),
            (b"cache-control", b"no-store"),
        ]
    await send(ev)

async def app(scope, receive, send):
    if scope["type"] != "http":
        return await mcp_asgi(scope, receive, send)

    method = scope.get("method", "GET").upper()
    path   = scope.get("path", "/")

    # Preflight CORS para /mcp
    if method == "OPTIONS" and (path == "/mcp" or path.startswith("/mcp")):
        await _cors_send(send, {"type":"http.response.start","status":204,"headers":[]})
        await send({"type":"http.response.body","body":b""})
        return

    # Health sencillo en "/"
    if method in ("GET","HEAD") and path == "/":
        body = json.dumps(_health_payload()).encode("utf-8")
        await _cors_send(send, {"type":"http.response.start","status":200,
                                "headers":[(b"content-type", b"application/json; charset=utf-8")]})
        if method == "GET":
            await send({"type":"http.response.body","body": body})
        else:
            await send({"type":"http.response.body","body": b""})
        return

    # TODO: NO reescribas /mcp -> /  (deja que mcp_asgi maneje /mcp)
    return await mcp_asgi(scope, receive, lambda ev: _cors_send(send, ev))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
