"""Janus Service Manager — Spawn, monitor, and proxy child MCP servers."""

import asyncio
import logging
import subprocess
import json
import os
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# Track running child server processes
_children: dict[str, dict] = {}


class ServiceManager:
    """Manages lifecycle and communication with child MCP server subprocesses."""

    def __init__(self, config: dict):
        self.config = config

    async def start_service(self, service_key: str) -> bool:
        """Start a child MCP server as a subprocess."""
        svc_config = self.config.get(service_key)
        if not svc_config:
            logger.warning("No config for service '%s'", service_key)
            return False

        definition = svc_config["definition"]
        auth = svc_config["auth"]
        command = definition.get("runner", "npx")
        args = list(definition.get("args", []))
        package = definition.get("package", "")
        if package:
            args = args + [package]

        # Build environment with auth tokens
        env = os.environ.copy()
        auth_type = auth.get("type", "")
        if auth_type in ("pat", "apikey"):
            env_var = definition.get("auth", {}).get("env_var", "")
            token = auth.get("token", "")
            if env_var and token:
                env[env_var] = token

        logger.info("Starting service '%s': %s %s", service_key, command, " ".join(args))

        try:
            proc = await asyncio.create_subprocess_exec(
                command,
                *args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                limit=1024 * 1024,  # 1MB buffer
            )

            # Perform MCP handshake
            async def _mcp_send(msg: dict) -> dict:
                line = json.dumps(msg) + "\n"
                proc.stdin.write(line.encode("utf-8"))
                await proc.stdin.drain()
                resp = await asyncio.wait_for(proc.stdout.readline(), timeout=15)
                return json.loads(resp.decode("utf-8"))

            # Initialize
            init_resp = await _mcp_send({
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "janus-mcp", "version": "0.1.0"},
                },
            })
            if "error" in init_resp:
                logger.error("Init failed for '%s': %s", service_key, init_resp["error"])
                proc.terminate()
                return False

            # Send initialized notification
            await _mcp_send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })

            # List tools
            tools_resp = await _mcp_send({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "list_tools",
                "params": {},
            })

            tools = tools_resp.get("result", {}).get("tools", [])

            _children[service_key] = {
                "proc": proc,
                "tools": tools,
                "definition": definition,
            }

            logger.info("Service '%s' connected with %d tools", service_key, len(tools))
            return True

        except Exception as e:
            logger.error("Failed to start service '%s': %s", service_key, e)
            _children[service_key] = {
                "error": str(e),
                "tools": [],
                "definition": definition,
            }
            return False

    def list_all_tools(self) -> list[dict]:
        """Aggregate tools from all connected services with janus_ prefix."""
        aggregated = []
        for key, child in _children.items():
            if child.get("error"):
                continue
            for tool in child.get("tools", []):
                prefixed = {
                    "name": f"janus_{key}_{tool['name']}",
                    "description": tool.get("description", ""),
                    "inputSchema": tool.get("inputSchema", {}),
                }
                aggregated.append(prefixed)
        return aggregated

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Route a tool call to the correct child server."""
        if not name.startswith("janus_"):
            return {"isError": True, "content": [{"type": "text", "text": f"Unknown tool: {name}"}]}

        parts = name.split("_", 2)
        if len(parts) < 3:
            return {"isError": True, "content": [{"type": "text", "text": f"Invalid tool name: {name}"}]}

        service_key = parts[1]
        child_tool_name = parts[2]

        child = _children.get(service_key)
        if not child:
            return {"isError": True, "content": [{"type": "text", "text": f"Service '{service_key}' is not connected. Run `janus connect {service_key}` first."}]}

        if child.get("error"):
            return {"isError": True, "content": [{"type": "text", "text": f"Service '{service_key}' error: {child['error']}"}]}

        # Send call_tool via the running subprocess's stdin/stdout
        try:
            proc = child["proc"]
            request = {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "call_tool",
                "params": {
                    "name": child_tool_name,
                    "arguments": arguments,
                },
            }

            # Run in executor to not block the event loop
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(self._sync_call, proc, request)
                result = future.result(timeout=120)

            return result

        except Exception as e:
            logger.error("Tool call failed for %s/%s: %s", service_key, child_tool_name, e)
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

    def _sync_call(self, proc, request: dict) -> dict:
        """Synchronous MCP call to a child process."""
        import json
        line = json.dumps(request) + "\n"
        proc.stdin.write(line.encode("utf-8"))
        proc.stdin.flush()
        resp = proc.stdout.readline()
        return json.loads(resp.decode("utf-8")) if resp else {"isError": True, "content": [{"type": "text", "text": "No response from child server"}]}

    def stop_all(self):
        """Terminate all child server processes."""
        for key, child in _children.items():
            if "proc" in child:
                try:
                    child["proc"].terminate()
                except Exception:
                    pass
        _children.clear()

    def get_status(self) -> list[dict]:
        """Get status of all services."""
        statuses = []
        for key, child in _children.items():
            statuses.append({
                "key": key,
                "name": child.get("definition", {}).get("name", key),
                "connected": "proc" in child and child["proc"].returncode is None,
                "tools": len(child.get("tools", [])),
                "error": child.get("error"),
            })
        return statuses
