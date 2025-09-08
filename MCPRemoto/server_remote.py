import os
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.sse import create_fastapi_app  # si tu SDK lo expone

mcp = FastMCP("hello-remote")

@mcp.tool()
def hello(nombre: str = "mundo") -> str:
    return f"Hola, {nombre} (desde MCP remoto) 👋"

@mcp.tool()
def ping() -> str:
    return "pong (remoto)"

app = create_fastapi_app(mcp)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
