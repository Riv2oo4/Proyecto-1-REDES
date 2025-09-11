
import os
import json
import subprocess
import time
import requests  
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional
import uuid
from typing import Optional
import anthropic

# ============== CONFIGURACIÓN ==============
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-4-1-20250805")

# URL del servidor remoto en Google Cloud Run
REMOTE_SERVER_URL = "https://mcp-hello-remote-py-145050194840.us-central1.run.app"

BASE_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = BASE_DIR / "workspace"
WORKSPACE_DIR.mkdir(exist_ok=True)

LOG_FILE = BASE_DIR / "chat_log.jsonl"
MCP_SESSION_ID: Optional[str] = None  #
REMOTE_TIMEOUT = 15   
WIRE_LOG = BASE_DIR / "wire_log.ndjson"

def _wire_log(event: str, data: Dict[str, Any]):
    try:
        with open(WIRE_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "event": event,
                **data
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _remote_headers(extra: Dict[str, str] = None) -> Dict[str, str]:
    h = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"  
    }
    global MCP_SESSION_ID
    if MCP_SESSION_ID:
        h["Mcp-Session-Id"] = MCP_SESSION_ID
    if extra:
        h.update(extra)
    return h


def mcp_request(method: str, params: Dict[str, Any]) -> requests.Response:
    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": method,
        "params": params
    }

    _wire_log("jsonrpc.request", {
        "url": f"{REMOTE_SERVER_URL}/mcp",
        "headers": _remote_headers(),           
        "body": payload
    })

    resp = requests.post(
        f"{REMOTE_SERVER_URL}/mcp",
        json=payload,
        headers=_remote_headers(),
        timeout=REMOTE_TIMEOUT
    )

    try:
        ct = (resp.headers.get("Content-Type") or "")
        body_text = resp.text
        base = {
            "status": resp.status_code,
            "ct": ct,
            "headers": dict(resp.headers),
        }

        if "text/event-stream" in ct.lower():
            chunks = []
            for ln in body_text.splitlines():
                if ln.startswith("data:"):
                    payload_line = ln[len("data:"):].strip()
                    if payload_line and payload_line != "[DONE]":
                        try:
                            chunks.append(json.loads(payload_line))
                        except Exception:
                            chunks.append({"raw": payload_line})
            _wire_log("jsonrpc.response.stream", {**base, "chunks": chunks})
        else:
            try:
                _wire_log("jsonrpc.response", {**base, "body_json": resp.json()})
            except Exception:
                _wire_log("jsonrpc.response", {**base, "body_text": body_text[:20000]})
    except Exception as e:
        _wire_log("jsonrpc.response.error", {"error": str(e)})

    return resp

def _parse_mcp_response(resp: requests.Response) -> Dict[str, Any]:
    ct = (resp.headers.get("Content-Type") or "").lower()

    if "application/json" in ct:
        try:
            return {"ok": True, "data": resp.json()}
        except Exception as e:
            return {"ok": False, "error": f"No JSON válido: {e}. Body={resp.text[:200]}"}

    if "text/event-stream" in ct:
        try:
            lines = resp.text.splitlines()
            json_candidates = []
            for ln in lines:
                if ln.startswith("data:"):
                    payload = ln[len("data:"):].strip()
                    if payload and payload != "[DONE]":
                        json_candidates.append(payload)

            # toma el último JSON válido
            for s in reversed(json_candidates):
                try:
                    return {"ok": True, "data": json.loads(s)}
                except Exception:
                    continue

            return {"ok": False, "error": f"No encontré JSON en SSE. Body={resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "error": f"Error parseando SSE: {e}"}

    body_snip = resp.text[:200] if resp.text else "<vacío>"
    return {"ok": False, "error": f"Content-Type inesperado '{ct}'. Body={body_snip}"}

def mcp_initialize() -> Dict[str, Any]:
    global MCP_SESSION_ID
    try:
        resp = mcp_request("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {}
        })
        MCP_SESSION_ID = resp.headers.get("Mcp-Session-Id")

        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        parsed = _parse_mcp_response(resp)
        if not parsed["ok"]:
            return {"ok": False, "error": parsed["error"]}

        return {"ok": True, "data": parsed["data"], "session": MCP_SESSION_ID}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def mcp_tools_list() -> List[str]:
    try:
        resp = mcp_request("tools/list", {})
        if resp.status_code != 200:
            return []
        parsed = _parse_mcp_response(resp)
        if not parsed["ok"]:
            return []
        data = parsed["data"]
        tools = data.get("result", {}).get("tools", [])
        return [t.get("name") for t in tools if isinstance(t, dict)]
    except Exception:
        return []

# ============== FUNCIONES SERVIDOR REMOTO ==============
def call_remote_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        resp = mcp_request("tools/call", {
            "name": tool_name,
            "arguments": arguments
        })

        if resp.status_code in (429, 503):
            time.sleep(1.5)
            resp = mcp_request("tools/call", {
                "name": tool_name,
                "arguments": arguments
            })

        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code}: {resp.text[:300]}"}

        parsed = _parse_mcp_response(resp)
        if not parsed["ok"]:
            return {"error": parsed["error"]}

        data = parsed["data"]
        if "error" in data:
            return {"error": str(data["error"])}
        result = data.get("result", {})


        result = data.get("result", {})
        # FastMCP suele devolver {"content":[{"type":"text","text":"..."}]}
        if isinstance(result, dict) and "content" in result:
            content = result["content"]
            if isinstance(content, list) and content and isinstance(content[0], dict):
                if "text" in content[0]:
                    return {"result": content[0]["text"]}
            return {"result": str(content)}
        # Si ya es texto plano
        if isinstance(result, str):
            return {"result": result}

        return {"result": json.dumps(result, ensure_ascii=False)}

    except requests.exceptions.Timeout:
        return {"error": "Timeout al conectar con el servidor remoto"}
    except Exception as e:
        return {"error": f"Error de conexión: {e}"}


def call_remote_echo(text: str) -> Dict[str, Any]:
    return call_remote_tool("echo", {"texto": text})

def call_remote_morse(text: str) -> Dict[str, Any]:
    return call_remote_tool("morse", {"texto": text})

def call_remote_demorse(code: str) -> Dict[str, Any]:
    return call_remote_tool("demorse", {"codigo": code})

def test_remote_server() -> bool:
    try:
        resp = requests.get(f"{REMOTE_SERVER_URL}/", timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            print(f"✅ Servidor remoto conectado: {data.get('kind','?')}  (mount {data.get('mount')})")
            print(f"   Herramientas (health): {', '.join(data.get('tools', []))}")
            return True
        else:
            print(f"⚠️  Health HTTP {resp.status_code}: {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"⚠️  No se pudo conectar al servidor remoto (health): {e}")
        return False


# ============== FUNCIONES DNS (locales) ==============
def call_dns_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    try:
        import sys
        sys.path.append(str(BASE_DIR))
        import servidor
        
        tools = {
            "ping": servidor.ping,
            "salud_dns": servidor.salud_dns,
            "correo_politicas": servidor.correo_politicas,
            "estado_dnssec": servidor.estado_dnssec,
            "propagacion": servidor.propagacion
        }
        
        if tool_name in tools:
            result = tools[tool_name](**arguments)
            return result
        else:
            return {"error": f"Herramienta {tool_name} no encontrada"}
            
    except Exception as e:
        return {"error": str(e)}

# ============== FUNCIONES FILESYSTEM ==============
def list_files(path: str = ".") -> Dict[str, Any]:
    try:
        target_path = WORKSPACE_DIR / path
        if not target_path.exists():
            return {"error": f"La ruta {path} no existe"}
        
        items = []
        for item in target_path.iterdir():
            items.append({
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None
            })
        
        return {"path": str(path), "items": items, "total": len(items)}
    except Exception as e:
        return {"error": str(e)}

def read_file(path: str) -> Dict[str, Any]:
    try:
        file_path = WORKSPACE_DIR / path
        if not file_path.exists():
            return {"error": f"El archivo {path} no existe"}
        
        content = file_path.read_text(encoding='utf-8')
        return {
            "path": str(path),
            "content": content,
            "lines": content.count('\n') + 1
        }
    except Exception as e:
        return {"error": str(e)}

def write_file(path: str, content: str) -> Dict[str, Any]:
    try:
        file_path = WORKSPACE_DIR / path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding='utf-8')
        
        return {
            "path": str(path),
            "written": True,
            "size": len(content)
        }
    except Exception as e:
        return {"error": str(e)}

def create_directory(path: str) -> Dict[str, Any]:
    try:
        dir_path = WORKSPACE_DIR / path
        dir_path.mkdir(parents=True, exist_ok=True)
        return {"path": str(path), "created": True}
    except Exception as e:
        return {"error": str(e)}

# ============== FUNCIONES GIT ==============
def run_git_command(args: List[str]) -> Dict[str, Any]:
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=WORKSPACE_DIR,
            capture_output=True,
            text=True,
            check=False
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout,
            "error": result.stderr if result.returncode != 0 else None
        }
    except FileNotFoundError:
        return {"success": False, "error": "Git no está instalado"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def git_init() -> Dict[str, Any]:
    result = run_git_command(["init"])
    if result["success"]:
        run_git_command(["config", "user.name", "MCP User"])
        run_git_command(["config", "user.email", "mcp@example.com"])
    return result

def git_status() -> Dict[str, Any]:
    return run_git_command(["status"])

def git_add(files: List[str] = None) -> Dict[str, Any]:
    if files is None or len(files) == 0:
        return run_git_command(["add", "."])
    else:
        return run_git_command(["add"] + files)

def git_commit(message: str) -> Dict[str, Any]:
    if not message:
        return {"success": False, "error": "Se requiere un mensaje"}
    return run_git_command(["commit", "-m", message])

def git_log(limit: int = 5) -> Dict[str, Any]:
    return run_git_command(["log", f"--max-count={limit}", "--oneline"])

# ============== CHATBOT ==============
class SimpleChatbot:
    def __init__(self):
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.conversation_history = []
        self.remote_available = False
        
    def initialize(self):
        print("\n🔍 Verificando servicios...")
        print("  • Servidor DNS local: ✅ Disponible")
        print("  • Sistema de archivos: ✅ Disponible")
        print("  • Git: ✅ Disponible")

        self.remote_available = test_remote_server()
        if self.remote_available:
            init_info = mcp_initialize()  
            if not init_info.get("ok"):
                print(f"  • MCP initialize: ❌ {init_info.get('error')}")
                self.remote_available = False
            else:
                print(f"  • MCP initialize: ✅ sesión={init_info.get('session') or 'stateless'}")
                self.remote_tools = mcp_tools_list() or ["echo", "morse", "demorse"]
                print(f"  • Tools remotos: {', '.join(self.remote_tools)}")

        
    def log_interaction(self, type: str, data: Any):
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "type": type,
                "data": data
            }, ensure_ascii=False) + '\n')
    
    def get_tools_description(self) -> str:
        base_tools = """
Tienes acceso a las siguientes herramientas:

**DNS (Local):**
- [DNS: ping] - Prueba de vida
- [DNS: salud_dns DOMINIO] - Análisis completo de DNS
- [DNS: correo_politicas DOMINIO] - Revisar MX/SPF/DMARC
- [DNS: estado_dnssec DOMINIO] - Verificar DNSSEC
- [DNS: propagacion DOMINIO] - Ver propagación

**Archivos:**
- [FILE: list] - Listar archivos
- [FILE: read ARCHIVO] - Leer archivo
- [FILE: write ARCHIVO "CONTENIDO"] - Escribir archivo
- [FILE: mkdir DIRECTORIO] - Crear directorio

**Git:**
- [GIT: init] - Inicializar repositorio
- [GIT: status] - Ver estado
- [GIT: add] - Añadir todos los archivos
- [GIT: commit "MENSAJE"] - Hacer commit
- [GIT: log] - Ver historial"""

        if self.remote_available:
            base_tools += """

**Servidor Remoto (Google Cloud):**
- [REMOTE: echo "TEXTO"] - Hace eco del texto
- [REMOTE: morse "TEXTO"] - Convierte texto a código morse
- [REMOTE: demorse "CODIGO"] - Decodifica código morse a texto

Ejemplos del servidor remoto:
[REMOTE: echo "Hola mundo"]
[REMOTE: morse "SOS"]
[REMOTE: demorse "... --- ..."]"""

        base_tools += """

Usa el formato exacto. Ejemplos:
[DNS: salud_dns google.com]
[FILE: write README.md "# Mi Proyecto"]
[GIT: commit "Initial commit"]
"""
        return base_tools
    
    def process_tool_calls(self, text: str) -> str:
        """Procesa las llamadas a herramientas en el texto"""
        import re
        
        # Patrones para cada tipo de herramienta
        patterns = [
            # DNS Local
            (r'\[DNS:\s*ping\]', lambda: call_dns_tool("ping", {})),
            (r'\[DNS:\s*salud_dns\s+(\S+)\]', lambda m: call_dns_tool("salud_dns", {"dominio": m.group(1)})),
            (r'\[DNS:\s*correo_politicas\s+(\S+)\]', lambda m: call_dns_tool("correo_politicas", {"dominio": m.group(1)})),
            (r'\[DNS:\s*estado_dnssec\s+(\S+)\]', lambda m: call_dns_tool("estado_dnssec", {"dominio": m.group(1)})),
            (r'\[DNS:\s*propagacion\s+(\S+)\]', lambda m: call_dns_tool("propagacion", {"dominio": m.group(1)})),
            
            # Archivos
            (r'\[FILE:\s*list\]', lambda: list_files()),
            (r'\[FILE:\s*read\s+(\S+)\]', lambda m: read_file(m.group(1))),
            (r'\[FILE:\s*write\s+(\S+)\s+"([^"]+)"\]', lambda m: write_file(m.group(1), m.group(2))),
            (r'\[FILE:\s*mkdir\s+(\S+)\]', lambda m: create_directory(m.group(1))),
            
            # Git
            (r'\[GIT:\s*init\]', lambda: git_init()),
            (r'\[GIT:\s*status\]', lambda: git_status()),
            (r'\[GIT:\s*add\]', lambda: git_add()),
            (r'\[GIT:\s*commit\s+"([^"]+)"\]', lambda m: git_commit(m.group(1))),
            (r'\[GIT:\s*log\]', lambda: git_log()),
            
            # Servidor Remoto
            # Servidor Remoto (CORRECTO)
            (r'\[REMOTE:\s*echo\s+"([^"]+)"\]', lambda m: call_remote_echo(m.group(1))),
            (r'\[REMOTE:\s*morse\s+"([^"]+)"\]', lambda m: call_remote_morse(m.group(1))),
            (r'\[REMOTE:\s*demorse\s+"([^"]+)"\]', lambda m: call_remote_demorse(m.group(1))),
        ]
        
        result_text = text
        
        for pattern, handler in patterns:
            matches = list(re.finditer(pattern, text))
            for match in reversed(matches):
                try:
                    if match.groups():
                        result = handler(match)
                    else:
                        result = handler()
                    
                    self.log_interaction("tool_call", {
                        "tool": match.group(0),
                        "result": result
                    })
                    
                    # Formatear resultado
                    if isinstance(result, dict):
                        if "error" in result:
                            result_str = f"\n❌ Error: {result['error']}\n"
                        elif "result" in result:
                            result_str = f"\n✅ Resultado: {result['result']}\n"
                        else:
                            result_str = f"\n✅ Resultado:\n{json.dumps(result, indent=2, ensure_ascii=False)}\n"
                    else:
                        result_str = f"\n✅ Resultado: {result}\n"
                    
                    result_text = result_text[:match.start()] + result_str + result_text[match.end():]
                    
                except Exception as e:
                    error_str = f"\n❌ Error ejecutando herramienta: {e}\n"
                    result_text = result_text[:match.start()] + error_str + result_text[match.end():]
        
        return result_text
    
    def chat(self, user_input: str) -> str:
        self.conversation_history.append({"role": "user", "content": user_input})
        
        system_prompt = f"""Eres un asistente útil con acceso a herramientas locales y remotas.

{self.get_tools_description()}

Responde de manera natural y usa las herramientas cuando sea necesario.
Mantén el contexto de la conversación."""
        
        try:
            response = self.client.messages.create(
                model=ANTHROPIC_MODEL,
                max_tokens=2000,
                system=system_prompt,
                messages=self.conversation_history
            )
            
            assistant_response = response.content[0].text
            final_response = self.process_tool_calls(assistant_response)
            
            self.conversation_history.append({"role": "assistant", "content": final_response})
            
            self.log_interaction("message", {
                "user": user_input,
                "assistant": final_response
            })
            
            return final_response
            
        except Exception as e:
            return f"Error: {e}"
    
    def run(self):
        print("=" * 60)
        print("🤖 CHATBOT CON SERVIDOR REMOTO")
        print("=" * 60)
        print(f"Modelo: {ANTHROPIC_MODEL}")
        print(f"Workspace: {WORKSPACE_DIR}")
        print(f"Log: {LOG_FILE}")
        print(f"Servidor remoto: {REMOTE_SERVER_URL}")
        print("=" * 60)
        
        self.initialize()
        
        print("\n📋 Herramientas disponibles:")
        print("  • DNS: análisis de dominios (local)")
        print("  • Archivos: crear, leer, listar (local)")
        print("  • Git: control de versiones (local)")
        if self.remote_available:
            print("  • Morse: codificar/decodificar (remoto)")
            print("  • Echo: repetir texto (remoto)")
        
        print("\n💬 Escribe 'salir' para terminar")
        print("=" * 60)
        
        while True:
            try:
                user_input = input("\n👤 Tú: ").strip()
                
                if user_input.lower() in ['salir', 'exit', 'quit']:
                    print("\n👋 ¡Hasta luego!")
                    break
                
                if not user_input:
                    continue
                
                print("\n🤔 Procesando...")
                response = self.chat(user_input)
                print(f"\n🤖 Asistente: {response}")
                
            except KeyboardInterrupt:
                print("\n\n👋 ¡Hasta luego!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")

# ============== DEMO ==============
def demo():
    """Ejecuta una demostración incluyendo servidor remoto"""
    chatbot = SimpleChatbot()
    chatbot.initialize()
    
    print("\n" + "=" * 60)
    print("📋 MODO DEMOSTRACIÓN (Local + Remoto)")
    print("=" * 60)
    
    demos = [
        "Hola, ¿qué herramientas tienes disponibles?",
        "Convierte 'HELLO WORLD' a código morse",
        "Decodifica este morse: ... --- ...",
        "Analiza la salud DNS de cloudflare.com",
        "Crea un archivo morse.txt con el código morse de SOS",
        "Lista los archivos",
        "Inicializa un repositorio Git y haz un commit"
    ]
    
    for i, prompt in enumerate(demos, 1):
        print(f"\n{'='*60}")
        print(f"Demo {i}/{len(demos)}: {prompt}")
        print("="*60)
        response = chatbot.chat(prompt)
        print(f"Respuesta: {response}")
        time.sleep(2)
    
    print("\n✅ Demostración completada")

# ============== MAIN ==============
def main():
    if not ANTHROPIC_API_KEY:
        print("❌ Error: Falta ANTHROPIC_API_KEY")
        print("\nConfigura tu API key:")
        print("  PowerShell: $env:ANTHROPIC_API_KEY='sk-ant-...'")
        print("\nObtén $5 gratis en: https://console.anthropic.com")
        return
    
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        demo()
    else:
        chatbot = SimpleChatbot()
        chatbot.run()

if __name__ == "__main__":
    main()