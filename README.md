# Janus MCP

**Self-hosted MCP connector hub** — aggregate, manage, and authenticate MCP servers under one namespace. No cloud, no broker, entirely self-hosted.

Janus is an MCP server that **spawns child MCP servers** (one per service) and aggregates their tools under `janus_*` names. It manages authentication tokens in an encrypted local vault.

## Quick Start

```bash
pip install janus-mcp

# Initialize the vault
janus vault init

# Search the community registry for services
janus search
janus search database

# Install and connect a service
janus install github
janus connect github
# → Paste your GitHub PAT

# Start the MCP aggregator
janus serve
```

Then add to any MCP client:

```yaml
# ~/.hermes/config.yaml (Hermes Agent)
mcp_servers:
  janus:
    command: janus
    args: ["serve"]
```

Or Claude Desktop:

```json
{
  "mcpServers": {
    "janus": {
      "command": "janus",
      "args": ["serve"]
    }
  }
}
```

Tools appear as:
- `janus_github_list_issues`
- `janus_brave_search_web`
- `janus_gmail_send_email`

## CLI Reference

| Command | Description |
|---------|-------------|
| `janus search [query]` | Search available services in the community registry |
| `janus info <service>` | Show full definition and setup instructions |
| `janus install <service>` | Download a service definition from the registry |
| `janus connect <service>` | Authenticate and enable a service |
| `janus remove <service>` | Disconnect and remove auth |
| `janus list` | Show installed services and their status |
| `janus update` | Pull latest registry INDEX.md |
| `janus serve` | Start MCP aggregator (stdio) |
| `janus vault init` | Initialize the encrypted token vault |

## Community Registry

Service definitions live in the **[janus-registry](https://github.com/Duskript/janus-registry)** repo — one YAML file per service, PR-driven. Adding a new service is as simple as:

```yaml
# services/my-service.yaml
name: My Service
package: some-mcp-server-package
runner: npx
auth:
  type: apikey
  env_var: MY_API_KEY
  setup_url: "https://example.com/api-keys"
category: "Dev Tools"
```

Fork, create the YAML, submit a PR. No code, no build step.

## Architecture

```
┌─────────────┐     stdio     ┌──────────────────────────────────┐
│ MCP Client  │◄───────────►│         Janus Aggregator           │
│ (Hermes,    │              │                                  │
│ Claude,     │              │  ┌──────────────────────────────┐ │
│ Codex...)   │              │  │  Service Manager             │ │
└─────────────┘              │  │  - Spawns child subprocesses │ │
                             │  │  - Proxies tools + calls     │ │
                             │  └──────────┬───────────────────┘ │
                             │             │                     │
                             │  ┌──────────▼───────────────────┐ │
                             │  │  Auth Vault (Fernet-encrypted) │ │
                             │  │  ~/.config/janus/vault        │ │
                             │  └────────────────────────────────┘ │
                             │                                     │
                             │  Subprocesses:                      │
                             │  ├── npx @mcp/server-github         │
                             │  ├── npx @mcp/server-brave-search   │
                             │  └── ...                            │
                             └─────────────────────────────────────┘
```

## Links

- **Registry:** [github.com/Duskript/janus-registry](https://github.com/Duskript/janus-registry)
- **Pantheon:** [github.com/Duskript/Pantheon](https://github.com/Duskript/Pantheon)
- **Issues:** [github.com/Duskript/janus-mcp/issues](https://github.com/Duskript/janus-mcp/issues)
