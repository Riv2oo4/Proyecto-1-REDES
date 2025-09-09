import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP

# Configuración
WORKSPACE_DIR = Path(os.environ.get("MCP_WORKSPACE", "./workspace"))
WORKSPACE_DIR.mkdir(exist_ok=True)

# Crear servidor MCP
mcp = FastMCP("Filesystem-Simple")

@mcp.tool(description="Lista archivos y directorios en una ruta")
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
        
        return {
            "path": str(path),
            "items": items,
            "total": len(items)
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Lee el contenido de un archivo")
def read_file(path: str) -> Dict[str, Any]:
    try:
        file_path = WORKSPACE_DIR / path
        if not file_path.exists():
            return {"error": f"El archivo {path} no existe"}
        
        if not file_path.is_file():
            return {"error": f"{path} no es un archivo"}
        
        content = file_path.read_text(encoding='utf-8')
        return {
            "path": str(path),
            "content": content,
            "size": len(content),
            "lines": content.count('\n') + 1
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Escribe contenido a un archivo")
def write_file(path: str, content: str) -> Dict[str, Any]:
    try:
        file_path = WORKSPACE_DIR / path
        
        # Crear directorios padre si no existen
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Escribir contenido
        file_path.write_text(content, encoding='utf-8')
        
        return {
            "path": str(path),
            "written": True,
            "size": len(content),
            "message": f"Archivo {path} escrito exitosamente"
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Crea un directorio")
def create_directory(path: str) -> Dict[str, Any]:
    try:
        dir_path = WORKSPACE_DIR / path
        if dir_path.exists():
            return {"error": f"El directorio {path} ya existe"}
        
        dir_path.mkdir(parents=True, exist_ok=True)
        return {
            "path": str(path),
            "created": True,
            "message": f"Directorio {path} creado exitosamente"
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Elimina un archivo o directorio")
def delete_item(path: str) -> Dict[str, Any]:
    try:
        item_path = WORKSPACE_DIR / path
        if not item_path.exists():
            return {"error": f"{path} no existe"}
        
        if item_path.is_file():
            item_path.unlink()
            return {"path": str(path), "deleted": True, "type": "file"}
        elif item_path.is_dir():
            import shutil
            shutil.rmtree(item_path)
            return {"path": str(path), "deleted": True, "type": "directory"}
        
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Mueve o renombra un archivo o directorio")
def move_item(source: str, destination: str) -> Dict[str, Any]:
    try:
        source_path = WORKSPACE_DIR / source
        dest_path = WORKSPACE_DIR / destination
        
        if not source_path.exists():
            return {"error": f"El origen {source} no existe"}
        
        # Crear directorios padre del destino si no existen
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        source_path.rename(dest_path)
        return {
            "source": str(source),
            "destination": str(destination),
            "moved": True,
            "message": f"Movido de {source} a {destination}"
        }
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Obtiene información sobre un archivo o directorio")
def get_info(path: str) -> Dict[str, Any]:
    try:
        item_path = WORKSPACE_DIR / path
        if not item_path.exists():
            return {"error": f"{path} no existe"}
        
        stat = item_path.stat()
        info = {
            "path": str(path),
            "type": "directory" if item_path.is_dir() else "file",
            "size": stat.st_size,
            "created": stat.st_ctime,
            "modified": stat.st_mtime,
            "accessed": stat.st_atime
        }
        
        if item_path.is_dir():
            # Contar elementos en el directorio
            items = list(item_path.iterdir())
            info["items_count"] = len(items)
            info["files_count"] = sum(1 for i in items if i.is_file())
            info["dirs_count"] = sum(1 for i in items if i.is_dir())
        
        return info
    except Exception as e:
        return {"error": str(e)}

@mcp.tool(description="Busca archivos por patrón en el workspace")
def search_files(pattern: str, path: str = ".") -> Dict[str, Any]:
    try:
        import glob
        search_path = WORKSPACE_DIR / path
        
        # Buscar recursivamente
        matches = []
        for match in search_path.rglob(pattern):
            relative_path = match.relative_to(WORKSPACE_DIR)
            matches.append({
                "path": str(relative_path),
                "type": "directory" if match.is_dir() else "file",
                "size": match.stat().st_size if match.is_file() else None
            })
        
        return {
            "pattern": pattern,
            "search_path": str(path),
            "matches": matches,
            "count": len(matches)
        }
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    import sys
    print(f"Servidor Filesystem MCP iniciando...")
    print(f"Workspace: {WORKSPACE_DIR.absolute()}")
    mcp.run()