import os
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Any, Optional
from mcp.server.fastmcp import FastMCP

# Configuración
WORKSPACE_DIR = Path(os.environ.get("MCP_WORKSPACE", "./workspace"))
WORKSPACE_DIR.mkdir(exist_ok=True)

# Crear servidor MCP
mcp = FastMCP("Git-Simple")

def run_git_command(args: List[str], cwd: Path = None) -> Dict[str, Any]:
    if cwd is None:
        cwd = WORKSPACE_DIR
    
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode
        }
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Git no está instalado en el sistema"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }

@mcp.tool(description="Inicializa un nuevo repositorio Git")
def git_init(path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    repo_path.mkdir(parents=True, exist_ok=True)
    
    result = run_git_command(["init"], repo_path)
    
    if result["success"]:
        # Configurar usuario por defecto si no está configurado
        run_git_command(["config", "user.name", "MCP User"], repo_path)
        run_git_command(["config", "user.email", "mcp@example.com"], repo_path)
        
        return {
            "initialized": True,
            "path": str(path),
            "message": f"Repositorio Git inicializado en {path}"
        }
    else:
        return {
            "initialized": False,
            "error": result.get("stderr", "Error desconocido")
        }

@mcp.tool(description="Muestra el estado del repositorio Git")
def git_status(path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    result = run_git_command(["status", "--porcelain"], repo_path)
    
    if result["success"]:
        lines = result["stdout"].strip().split("\n") if result["stdout"].strip() else []
        
        files = {
            "modified": [],
            "added": [],
            "deleted": [],
            "untracked": [],
            "renamed": []
        }
        
        for line in lines:
            if not line:
                continue
            status = line[:2]
            filename = line[3:]
            
            if status == "??":
                files["untracked"].append(filename)
            elif status[0] == "M" or status[1] == "M":
                files["modified"].append(filename)
            elif status[0] == "A":
                files["added"].append(filename)
            elif status[0] == "D":
                files["deleted"].append(filename)
            elif status[0] == "R":
                files["renamed"].append(filename)
        
        # También obtener la rama actual
        branch_result = run_git_command(["branch", "--show-current"], repo_path)
        current_branch = branch_result["stdout"].strip() if branch_result["success"] else "main"
        
        return {
            "branch": current_branch,
            "files": files,
            "clean": len(lines) == 0,
            "summary": f"{len(files['untracked'])} sin seguimiento, {len(files['modified'])} modificados, {len(files['added'])} añadidos"
        }
    else:
        return {
            "error": "No es un repositorio Git o error al obtener estado",
            "details": result.get("stderr", "")
        }

@mcp.tool(description="Añade archivos al área de staging")
def git_add(files: List[str] = None, path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    
    if files is None or len(files) == 0:
        # Añadir todos los archivos
        args = ["add", "."]
    else:
        # Añadir archivos específicos
        args = ["add"] + files
    
    result = run_git_command(args, repo_path)
    
    if result["success"]:
        return {
            "added": True,
            "files": files or ["todos"],
            "message": f"Archivos añadidos al staging"
        }
    else:
        return {
            "added": False,
            "error": result.get("stderr", "Error al añadir archivos")
        }

@mcp.tool(description="Realiza un commit con los cambios en staging")
def git_commit(message: str, path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    
    if not message:
        return {"error": "Se requiere un mensaje para el commit"}
    
    result = run_git_command(["commit", "-m", message], repo_path)
    
    if result["success"]:
        # Obtener el hash del commit
        hash_result = run_git_command(["rev-parse", "HEAD"], repo_path)
        commit_hash = hash_result["stdout"].strip()[:7] if hash_result["success"] else "unknown"
        
        return {
            "committed": True,
            "hash": commit_hash,
            "message": message,
            "output": result["stdout"]
        }
    else:
        if "nothing to commit" in result.get("stdout", ""):
            return {
                "committed": False,
                "message": "No hay cambios para hacer commit"
            }
        return {
            "committed": False,
            "error": result.get("stderr", "Error al hacer commit")
        }

@mcp.tool(description="Muestra el historial de commits")
def git_log(limit: int = 10, path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    
    result = run_git_command(
        ["log", f"--max-count={limit}", "--pretty=format:%H|%an|%ae|%at|%s"],
        repo_path
    )
    
    if result["success"]:
        commits = []
        for line in result["stdout"].strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 5:
                commits.append({
                    "hash": parts[0][:7],
                    "author": parts[1],
                    "email": parts[2],
                    "timestamp": parts[3],
                    "message": parts[4]
                })
        
        return {
            "commits": commits,
            "count": len(commits),
            "limit": limit
        }
    else:
        return {
            "error": "No es un repositorio Git o error al obtener historial",
            "details": result.get("stderr", "")
        }

@mcp.tool(description="Crea una nueva rama")
def git_branch(branch_name: str, checkout: bool = False, path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    
    if checkout:
        result = run_git_command(["checkout", "-b", branch_name], repo_path)
    else:
        result = run_git_command(["branch", branch_name], repo_path)
    
    if result["success"]:
        return {
            "created": True,
            "branch": branch_name,
            "checked_out": checkout,
            "message": f"Rama '{branch_name}' creada" + (" y activada" if checkout else "")
        }
    else:
        return {
            "created": False,
            "error": result.get("stderr", "Error al crear rama")
        }

@mcp.tool(description="Cambia a otra rama")
def git_checkout(branch_name: str, path: str = ".") -> Dict[str, Any]:
    repo_path = WORKSPACE_DIR / path
    
    result = run_git_command(["checkout", branch_name], repo_path)
    
    if result["success"]:
        return {
            "switched": True,
            "branch": branch_name,
            "message": f"Cambiado a rama '{branch_name}'"
        }
    else:
        return {
            "switched": False,
            "error": result.get("stderr", "Error al cambiar de rama")
        }

@mcp.tool(description="Lista todas las ramas")
def git_branches(path: str = ".") -> Dict[str, Any]:
    """Lista todas las ramas del repositorio"""
    repo_path = WORKSPACE_DIR / path
    
    result = run_git_command(["branch", "-a"], repo_path)
    
    if result["success"]:
        branches = []
        current = None
        
        for line in result["stdout"].strip().split("\n"):
            if not line:
                continue
            if line.startswith("*"):
                current = line[2:].strip()
                branches.append(current)
            else:
                branches.append(line.strip())
        
        return {
            "branches": branches,
            "current": current,
            "count": len(branches)
        }
    else:
        return {
            "error": "No es un repositorio Git o error al listar ramas",
            "details": result.get("stderr", "")
        }

@mcp.tool(description="Muestra las diferencias en archivos modificados")
def git_diff(staged: bool = False, path: str = ".") -> Dict[str, Any]:
    """Muestra las diferencias en los archivos modificados"""
    repo_path = WORKSPACE_DIR / path
    
    args = ["diff"]
    if staged:
        args.append("--staged")
    
    result = run_git_command(args, repo_path)
    
    if result["success"]:
        return {
            "diff": result["stdout"],
            "staged": staged,
            "has_changes": bool(result["stdout"].strip())
        }
    else:
        return {
            "error": "Error al obtener diferencias",
            "details": result.get("stderr", "")
        }

if __name__ == "__main__":
    import sys
    print(f"Servidor Git MCP iniciando...")
    print(f"Workspace: {WORKSPACE_DIR.absolute()}")
    mcp.run()