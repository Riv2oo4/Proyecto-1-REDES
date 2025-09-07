# MCP-DNS — README corto

Servidor **Model Context Protocol (MCP)** para diagnóstico de **DNS**, pensado para usarse con cualquier **cliente/anfitrión MCP** (Inspector, tu propio chatbot, etc.).

---

## 1) Especificación

* **Nombre del servidor:** `MCP-DNS`
* **Protocolo:** MCP por **STDIO**
* **Lenguaje:** Python 3.11+
* **Archivo principal:** `MCPLocal/servidor.py`
* **Auto-deps:** el archivo define
  `dependencies = ["dnspython>=2.6.1","cryptography>=42.0.0"]`
  para que el CLI de MCP las instale automáticamente.

### Tools expuestas

| Tool               | Parámetros                            | Qué hace                                                                    | Devuelve (JSON)                                                                   |
| ------------------ | ------------------------------------- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| `ping`             | —                                     | Prueba de vida                                                              | `"pong"`                                                                          |
| `salud_dns`        | `dominio: str`                        | A/AAAA/NS/SOA (recursivo y autoritativo), wildcard, TTLs, CNAME colgante    | `{recursivo, autoritativo, hallazgos}`                                            |
| `correo_politicas` | `dominio: str`                        | Revisa **MX**, **SPF**, **DMARC**                                           | `{mx, spf, dmarc, hallazgos}`                                                     |
| `estado_dnssec`    | `dominio: str`                        | DS en padre, DNSKEY, verificación DS↔DNSKEY, valida firma de SOA            | `{tiene_ds_en_padre, dnskey_algoritmos, soa_firmada_valida, detalles, hallazgos}` |
| `propagacion`      | `dominio: str`, `resolutores?: [str]` | Compara A/AAAA/NS entre resolutores (1.1.1.1, 8.8.8.8, 9.9.9.9 por defecto) | `{resolutores, respuestas, diferencias}`                                          |

---

## 2) Instalación (rápida)

Recomendado: entorno virtual.

```powershell
# Ubícate en la carpeta del proyecto
cd "C:\Users\TUUsuario\Ruta\Proyecto-1-REDES"

# Crea y activa venv (ejemplo .venv311)
py -3.11 -m venv .venv311
.\.venv311\Scripts\Activate.ps1

# Instala el CLI de MCP (incluye Inspector)
pip install -U "mcp[cli]"
```

> Las dependencias del servidor se auto-instalan al correr `mcp dev`/`mcp run` gracias al bloque `dependencies` del `servidor.py`.
> Alternativa manual: `pip install -U dnspython cryptography`

---

## 3) Cómo ejecutar

### A) Abrir Inspector automáticamente

```powershell
mcp dev .\MCPLocal\servidor.py
```

Se abrirá el **MCP Inspector** con el servidor corriendo.

### B) Conectar Inspector por STDIO (manual)

1. Abrir Inspector → **New connection** → **STDIO**
2. **Command:** `C:\...\Proyecto-1-REDES\.venv311\Scripts\mcp.exe`
   **Args:** `run "C:\...\Proyecto-1-REDES\MCPLocal\servidor.py"`
3. Conectar y usar las tools.
   **Nota:** En STDIO usa **`run`** (no `dev`).

### C) Desde un chat/cliente MCP propio

* Lanzamiento:

  ```bash
  mcp run /ruta/a/MCPLocal/servidor.py
  ```
* Invocación (pseudocódigo):

  ```python
  result = await session.call_tool("salud_dns", {"dominio": "example.com"})
  # result.content[0] → JSON con recursivo/autoritativo/hallazgos
  ```

---

## 4) Ejemplos de uso (Inspector → Tools → Run)

* `ping`
  **Resultado:** `"pong"`

* `salud_dns`
  **Input:** `{"dominio":"cloudflare.com"}`

* `correo_politicas`
  **Input:** `{"dominio":"example.com"}`

* `estado_dnssec`
  **Input:** `{"dominio":"cloudflare.com"}`

* `propagacion`
  **Input:**

  ```json
  {"dominio":"pool.ntp.org","resolutores":["1.1.1.1","8.8.8.8"]}
  ```

---

## 5) Logs y solución de problemas

* **Log JSONL:** `dns_mcp.log.jsonl`
  Ver últimos eventos:

  ```powershell
  Get-Content -Tail 50 .\dns_mcp.log.jsonl
  ```
* **“Unexpected token …” en Inspector:** en conexión STDIO usa **`run`**, no `dev`.
* **`No module named dns/cryptography`:** activa venv e instala manualmente:
  `pip install -U dnspython cryptography`
* **Timeout/NoAnswer:** reintenta o prueba otro dominio (firewall/UDP).

---

## 6) Estructura mínima del repo

```
Proyecto-1-REDES/
├─ MCPLocal/
│  ├─ servidor.py      # servidor MCP (este)
│  └─ host_llm.py      # (opcional) host de consola con lenguaje natural
└─ README.md
```

Listo. Con esto cualquier compañero puede **instalar, correr** e **integrar** el servidor en su propio chat/cliente MCP.
