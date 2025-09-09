# MCP Chatbot with Anthropic Claude

A console-based chatbot that integrates multiple MCP (Model Context Protocol) servers to extend Claude's capabilities with real-world tools for DNS analysis, file management, Git operations, and remote services.

## Features

### Core Functionality
- **LLM Integration**: Direct API connection with Anthropic's Claude models
- **Context Management**: Maintains conversation context across multiple interactions
- **Comprehensive Logging**: All MCP server interactions are logged in JSONL format
- **Multi-Server Architecture**: Supports simultaneous connection to multiple MCP servers

### MCP Servers Implemented

#### 1. DNS Analysis Server (Local)
Custom MCP server for comprehensive DNS operations:
- Domain health checks (A/AAAA/NS/SOA records)
- Email policy verification (MX/SPF/DMARC)
- DNSSEC validation
- DNS propagation monitoring
- Wildcard detection and CNAME validation

#### 2. Filesystem Server (Local)
File and directory management capabilities:
- List, read, write, and delete files
- Directory creation and navigation
- File search with pattern matching
- Metadata retrieval

#### 3. Git Server (Local)
Version control operations:
- Repository initialization
- Status monitoring
- Staging and committing changes
- Branch management
- Commit history viewing

#### 4. Remote Server (Google Cloud Run)
Deployed on Google Cloud Platform with:
- Text echo functionality
- Morse code encoding/decoding
- HTTP/JSON-RPC communication

## Prerequisites

- Python 3.8 or higher
- Git
- Google Cloud account (for remote server deployment)
- Anthropic API key (free $5 credits available upon registration)

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/yourusername/mcp-chatbot.git
cd mcp-chatbot
```

### 2. Create Virtual Environment
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```

Required packages:
- `anthropic>=0.18.0`
- `mcp>=0.1.0`
- `dnspython>=2.6.1`
- `cryptography>=42.0.0`
- `requests>=2.24.0`
- `httpx>=0.24.0`

### 4. Configure API Keys

#### Windows (PowerShell):
```powershell
$env:ANTHROPIC_API_KEY="sk-ant-api03-xxxxx"
$env:ANTHROPIC_MODEL="claude-opus-4-1-20250805"
```

#### Linux/Mac:
```bash
export ANTHROPIC_API_KEY="sk-ant-api03-xxxxx"
export ANTHROPIC_MODEL="claude-opus-4-1-20250805"
```

## Usage

### Running the Chatbot
```bash
python host.py
```

### Demo Mode
Run a demonstration of all features:
```bash
python host.py --demo
```

### Example Commands

#### DNS Operations:
- "Analyze DNS health for google.com"
- "Check email policies for microsoft.com"
- "Verify DNSSEC status for cloudflare.com"
- "Check DNS propagation for example.com"

#### File Operations:
- "List all files in the workspace"
- "Create a README.md file with project information"
- "Read the contents of config.json"
- "Search for all .txt files"

#### Git Operations:
- "Initialize a new Git repository"
- "Show repository status"
- "Add all files and commit with message 'Initial commit'"
- "Show commit history"

#### Remote Operations:
- "Convert 'HELLO WORLD' to morse code"
- "Decode morse: ... --- ..."
- "Echo 'Test message'"

### Complete Workflow Example
```
1. "Create a new Git repository"
2. "Create a README.md with the title 'MCP Project'"
3. "Analyze DNS health for my-domain.com"
4. "Save the DNS analysis results to dns_report.txt"
5. "Add all files to Git"
6. "Commit with message 'Initial project setup'"
7. "Convert the domain name to morse code"
```

## Project Structure
```
mcp-chatbot/
├── MCPLocal/
│   ├── servers/                 # Official Anthropic MCP servers
│   │   └── src/
│   │       ├── filesystem/
│   │       └── git/
│   ├── host.py              # Main chatbot application
│   ├── servidor.py          # DNS MCP server
│   ├── servidor_filesystem.py # Filesystem operations
│   ├── servidor_git.py      # Git operations
│   └── workspace/           # Working directory for files
├── MCPRemoto/
│   ├── server_remote.py     # Remote server code
│   ├── requirements.txt     # Remote server dependencies
│   └── Dockerfile           # Container configuration
├── chat_log.jsonl          # Interaction logs
└── README.md
```

## Remote Server Deployment (Google Cloud Run)

### 1. Build and Deploy
```bash
cd MCPRemoto
gcloud builds submit --tag gcr.io/$PROJECT_ID/mcp-remote
gcloud run deploy mcp-remote \
  --image gcr.io/$PROJECT_ID/mcp-remote \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```

### 2. Update Remote URL
Update `REMOTE_SERVER_URL` in `host.py` with your deployment URL.

## Available Models

| Model | API Name | Cost per 1M tokens |
|-------|----------|-------------------|
| Claude Opus 4.1 | `claude-opus-4-1-20250805` | $15/$75 |
| Claude Opus 4 | `claude-opus-4-20250805` | Standard pricing |
| Claude Sonnet 4 | `claude-sonnet-4-20250805` | Lower cost option |

## Logging

All interactions are logged in `chat_log.jsonl` with:
- Timestamp
- Request/response data
- Tool calls and results
- Execution duration

View logs:
```bash
tail -f chat_log.jsonl | jq '.'
```

## Troubleshooting

### "ANTHROPIC_API_KEY not found"
Ensure the environment variable is set before running the chatbot.

### "Git not installed"
Install Git from https://git-scm.com/downloads

### Remote server connection issues
- Verify the server is deployed: `curl https://your-server.run.app/mcp/`
- Check Google Cloud logs: `gcloud run services logs read mcp-remote`

### MCP server initialization errors
- Ensure all dependencies are installed
- Check that `servidor.py` is in the same directory as `host.py`
- Verify Python version compatibility (3.8+)

## Development

### Adding New MCP Servers
1. Create a new server file following the MCP protocol
2. Add server configuration to `MCP_SERVERS` dict in `host.py`
3. Implement tool call handlers
4. Update documentation

### Testing
Run tests for individual components:
```bash
python test_scenario.py
```

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

