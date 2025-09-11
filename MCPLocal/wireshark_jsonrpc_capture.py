import os
import json
import time
import requests
from datetime import datetime
from pathlib import Path
import uuid
from typing import Dict, Any, List
import logging
from urllib.parse import urlparse

# ============== CONFIGURACIÓN ==============
REMOTE_SERVER_URL = "https://mcp-hello-remote-py-145050194840.us-central1.run.app"
LOG_DIR = Path("jsonrpc_captures")
LOG_DIR.mkdir(exist_ok=True)

# Configurar logging detallado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_DIR / "jsonrpc_debug.log"),
        logging.StreamHandler()
    ]
)

class JSONRPCAnalyzer:
    
    def __init__(self, server_url: str):
        self.server_url = server_url
        self.session_id = None
        self.capture_file = LOG_DIR / f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        self.messages = []
        self.message_counter = 0
        
        # Crear sesión con hooks para logging
        self.session = requests.Session()
        self.session.hooks['response'] = [self.log_response]
        
    def log_response(self, resp, *args, **kwargs):
        self.message_counter += 1
        
        # Información de la petición
        request_info = {
            "message_num": self.message_counter,
            "timestamp": datetime.now().isoformat(),
            "direction": "REQUEST",
            "method": resp.request.method,
            "url": resp.request.url,
            "headers": dict(resp.request.headers),
            "body": None
        }
        
        # Intentar parsear el body de la petición
        if resp.request.body:
            try:
                if isinstance(resp.request.body, bytes):
                    body_str = resp.request.body.decode('utf-8')
                else:
                    body_str = resp.request.body
                request_info["body"] = json.loads(body_str)
                request_info["jsonrpc_type"] = self.classify_jsonrpc_message(request_info["body"])
            except:
                request_info["body"] = str(resp.request.body)[:500]
        
        # Información de la respuesta
        response_info = {
            "message_num": self.message_counter,
            "timestamp": datetime.now().isoformat(),
            "direction": "RESPONSE",
            "status_code": resp.status_code,
            "headers": dict(resp.headers),
            "body": None,
            "latency_ms": resp.elapsed.total_seconds() * 1000
        }
        
        # Intentar parsear el body de la respuesta
        try:
            response_info["body"] = resp.json()
            response_info["jsonrpc_type"] = self.classify_jsonrpc_message(response_info["body"])
        except:
            response_info["body"] = resp.text[:500]
        
        # Guardar mensajes
        self.messages.append(request_info)
        self.messages.append(response_info)
        
        # Log detallado
        logging.info(f"={'='*60}")
        logging.info(f"MESSAGE #{self.message_counter}")
        logging.info(f"{'='*60}")
        logging.info(f"REQUEST: {request_info['method']} {request_info['url']}")
        if request_info.get('jsonrpc_type'):
            logging.info(f"Type: {request_info['jsonrpc_type']}")
        if request_info.get('body') and isinstance(request_info['body'], dict):
            logging.info(f"JSONRPC Method: {request_info['body'].get('method', 'N/A')}")
            logging.info(f"ID: {request_info['body'].get('id', 'N/A')}")
        
        logging.info(f"RESPONSE: {response_info['status_code']} in {response_info['latency_ms']:.2f}ms")
        if response_info.get('jsonrpc_type'):
            logging.info(f"Type: {response_info['jsonrpc_type']}")
        
        # Guardar en archivo
        self.save_capture()
        
    def classify_jsonrpc_message(self, body: Any) -> str:
        if not isinstance(body, dict):
            return "NON_JSONRPC"
        
        # Peticiones
        if "method" in body:
            method = body.get("method", "")
            
            # Mensajes de sincronización/inicialización
            if method == "initialize":
                return "SYNC_INITIALIZE"
            elif method == "initialized":
                return "SYNC_INITIALIZED"
            elif method == "shutdown":
                return "SYNC_SHUTDOWN"
            
            # Peticiones de herramientas
            elif method == "tools/list":
                return "REQUEST_LIST_TOOLS"
            elif method == "tools/call":
                tool_name = body.get("params", {}).get("name", "unknown")
                return f"REQUEST_CALL_TOOL_{tool_name}"
            
            # Otros métodos
            else:
                return f"REQUEST_{method.upper()}"
        
        # Respuestas
        elif "result" in body or "error" in body:
            if "result" in body:
                # Intentar identificar el tipo de respuesta
                result = body.get("result", {})
                if isinstance(result, dict):
                    if "capabilities" in result:
                        return "RESPONSE_INITIALIZE"
                    elif "tools" in result:
                        return "RESPONSE_LIST_TOOLS"
                    elif "content" in result:
                        return "RESPONSE_TOOL_CALL"
                return "RESPONSE_SUCCESS"
            else:
                return "RESPONSE_ERROR"
        
        return "UNKNOWN_JSONRPC"
    
    def make_request(self, method: str, params: Dict[str, Any]) -> requests.Response:
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params
        }
        
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        
        logging.info(f"\n🔵 Enviando: {method}")
        
        resp = self.session.post(
            f"{self.server_url}/mcp",
            json=payload,
            headers=headers,
            timeout=15
        )
        
        # Capturar session ID si existe
        if "Mcp-Session-Id" in resp.headers:
            self.session_id = resp.headers["Mcp-Session-Id"]
            logging.info(f"📌 Session ID: {self.session_id}")
        
        return resp
    
    def save_capture(self):
        with open(self.capture_file, 'w', encoding='utf-8') as f:
            json.dump({
                "server_url": self.server_url,
                "capture_time": datetime.now().isoformat(),
                "total_messages": len(self.messages),
                "messages": self.messages
            }, f, indent=2, ensure_ascii=False)
    
    def run_test_scenario(self):
        print("\n" + "="*60)
        print("🔬 ESCENARIO DE PRUEBA JSONRPC")
        print("="*60)
        
        scenarios = [
            ("1. INICIALIZACIÓN", "initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {}
            }),
            ("2. LISTAR HERRAMIENTAS", "tools/list", {}),
            ("3. LLAMAR ECHO", "tools/call", {
                "name": "echo",
                "arguments": {"texto": "Hola desde Wireshark analysis"}
            }),
            ("4. LLAMAR MORSE", "tools/call", {
                "name": "morse",
                "arguments": {"texto": "SOS"}
            }),
            ("5. LLAMAR DEMORSE", "tools/call", {
                "name": "demorse",
                "arguments": {"codigo": "... --- ..."}
            }),
        ]
        
        for title, method, params in scenarios:
            print(f"\n{title}")
            print("-" * 40)
            
            try:
                resp = self.make_request(method, params)
                
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                        if "result" in data:
                            print(f"✅ Éxito: {json.dumps(data['result'], ensure_ascii=False)[:100]}")
                        elif "error" in data:
                            print(f"❌ Error: {data['error']}")
                    except:
                        print(f"✅ Respuesta: {resp.text[:100]}")
                else:
                    print(f"❌ HTTP {resp.status_code}")
                    
            except Exception as e:
                print(f"❌ Excepción: {e}")
            
            time.sleep(0.5)  # Pausa para mejor visualización
        
        print("\n" + "="*60)
        print("📊 RESUMEN DE CAPTURA")
        print("="*60)
        self.print_summary()
    
    def print_summary(self):
        message_types = {}
        
        for msg in self.messages:
            msg_type = msg.get("jsonrpc_type", "UNKNOWN")
            if msg_type not in message_types:
                message_types[msg_type] = 0
            message_types[msg_type] += 1
        
        print(f"\n📁 Archivo de captura: {self.capture_file}")
        print(f"📨 Total de mensajes: {len(self.messages)}")
        print(f"📤 Peticiones: {len([m for m in self.messages if m['direction'] == 'REQUEST'])}")
        print(f"📥 Respuestas: {len([m for m in self.messages if m['direction'] == 'RESPONSE'])}")
        
        print("\n📊 Tipos de mensajes JSONRPC:")
        for msg_type, count in sorted(message_types.items()):
            icon = "🔄" if "SYNC" in msg_type else "📮" if "REQUEST" in msg_type else "📬"
            print(f"  {icon} {msg_type}: {count}")
        
        # Latencias
        latencies = [m['latency_ms'] for m in self.messages 
                    if m.get('direction') == 'RESPONSE' and 'latency_ms' in m]
        if latencies:
            print(f"\n⏱️ Latencias:")
            print(f"  Min: {min(latencies):.2f}ms")
            print(f"  Max: {max(latencies):.2f}ms")
            print(f"  Avg: {sum(latencies)/len(latencies):.2f}ms")

def main():
    print("="*60)
    print("🔍 ANALIZADOR DE TRÁFICO JSONRPC")
    print("="*60)
    print(f"Servidor: {REMOTE_SERVER_URL}")
    print(f"Logs en: {LOG_DIR}/")
    
    analyzer = JSONRPCAnalyzer(REMOTE_SERVER_URL)
    
    # Ejecutar escenario de prueba
    analyzer.run_test_scenario()
    
    print("\n" + "="*60)
    print("✅ ANÁLISIS COMPLETADO")
    print("="*60)
    print(f"\n📋 Archivos generados:")
    print(f"  1. {analyzer.capture_file} - Captura JSON completa")
    print(f"  2. {LOG_DIR}/jsonrpc_debug.log - Log detallado")
    
    print("\n💡 Para analizar con Wireshark:")
    print("  1. Abre Wireshark")
    print("  2. Captura en tu interfaz de red")
    print("  3. Filtro: 'http.host contains \"run.app\" and http'")
    print("  4. O usa: 'tcp.port == 443 and ip.dst == <IP_del_servidor>'")
    
    print("\n📊 Los mensajes JSONRPC capturados son:")
    print("  • SYNC_INITIALIZE - Sincronización inicial")
    print("  • REQUEST_LIST_TOOLS - Petición de herramientas")
    print("  • REQUEST_CALL_TOOL_* - Llamadas a herramientas")
    print("  • RESPONSE_* - Respuestas del servidor")

if __name__ == "__main__":
    main()