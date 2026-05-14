"""Janus Server — MCP aggregator (stdio mode)."""

import json
import logging
import sys
import threading

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("janus")


def _load_config():
    """Load installed services and their auth from vault."""
    from .registry import registry_get_all_local
    from .vault import vault_get

    services = registry_get_all_local()
    config = {}
    for svc in services:
        key = svc["key"]
        auth = vault_get(key)
        if not auth:
            continue
        config[key] = {
            "definition": svc,
            "auth": auth,
        }
    return config


def _connect_children(manager):
    """Connect all child services in background threads."""
    for key in manager.config:
        t = threading.Thread(target=manager.start_service, args=(key,), daemon=True)
        t.start()


def run_server():
    """Run Janus in stdio MCP server mode."""
    from .service_manager import ServiceManager

    config = _load_config()
    manager = ServiceManager(config)

    logger.info("Starting Janus MCP aggregator (stdio)...")
    logger.info("Found %d connected services, will spawn in background", len(config))

    initialized = False

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        request_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "initialize":
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "sampling": {}},
                    "serverInfo": {"name": "janus-mcp", "version": "0.1.0"},
                },
            }
            initialized = True

        elif method == "notifications/initialized":
            # Client has accepted our init — now spawn children
            if not initialized:
                continue
            initialized = True  # mark as truly ready
            _connect_children(manager)
            continue  # No response needed

        elif method == "tools/list":
            tools = manager.list_all_tools()
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": {"tools": tools},
            }

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            result = manager.call_tool(tool_name, arguments)
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result if "isError" not in result else result,
            }

        else:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            }

        # Don't log method calls, just write response
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


def run_http_server(port: int = 8011):
    """Run Janus as an HTTP SSE server (placeholder)."""
    logger.info("HTTP server not yet implemented. Use stdio mode (`janus serve`).")
    sys.exit(1)
