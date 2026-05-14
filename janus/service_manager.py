"""Janus Service Manager — Spawn, monitor, and proxy child MCP servers."""

import logging
import subprocess
import json
import os
import select
import time
import threading

logger = logging.getLogger(__name__)

# Track running child server processes
_children: dict[str, dict] = {}
_children_lock = threading.Lock()


class ServiceManager:
    """Manages lifecycle and communication with child MCP server subprocesses."""

    def __init__(self, config: dict):
        self.config = config

    def start_service(self, service_key: str) -> bool:
        """Start a child MCP server as a subprocess (blocking, runs in thread)."""
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
            # Insert package right after runner flags (e.g., -y)
            # Find the first non-flag arg position
            pkg_in_args = any(package in arg for arg in args)
            if not pkg_in_args:
                insert_at = 0
                for i, arg in enumerate(args):
                    if arg.startswith("-"):
                        insert_at = i + 1
                    else:
                        break
                args.insert(insert_at, package)

        # Build environment with auth tokens
        env = os.environ.copy()
        auth_type = auth.get("type", "")
        if auth_type in ("pat", "apikey"):
            env_var = definition.get("auth", {}).get("env_var", "")
            token = auth.get("token", "")
            if env_var and token:
                env[env_var] = token

        logger.info("Spawning '%s': %s %s", service_key, command, " ".join(args))

        try:
            proc = subprocess.Popen(
                [command] + args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError:
            logger.error("Command not found for '%s': %s", service_key, command)
            with _children_lock:
                _children[service_key] = {"error": f"Command not found: {command}", "tools": [], "definition": definition}
            return False

        # MCP handshake
        try:
            # 1. Initialize
            init_resp = self._send_sync(proc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "janus-mcp", "version": "0.1.0"},
                },
            })
            if not init_resp or "error" in init_resp:
                err_msg = init_resp.get("error", "unknown") if init_resp else "no response"
                logger.error("Init failed for '%s': %s", service_key, err_msg)
                proc.terminate()
                return False

            # 2. Send initialized notification (no response expected)
            self._send_sync(proc, {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            }, expect_response=False)

            # 3. List tools
            tools_resp = self._send_sync(proc, {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/list",
                "params": {},
            })
            tools = tools_resp.get("result", {}).get("tools", []) if tools_resp else []

            with _children_lock:
                _children[service_key] = {
                    "proc": proc,
                    "tools": tools,
                    "definition": definition,
                }

            logger.info("Connected '%s' (%d tools)", service_key, len(tools))
            return True

        except Exception as e:
            logger.error("Failed to start '%s': %s", service_key, e)
            with _children_lock:
                _children[service_key] = {"error": str(e), "tools": [], "definition": definition}
            return False

    def _send_sync(self, proc, msg: dict, expect_response: bool = True) -> dict | None:
        """Send a JSON-RPC message to a child process and optionally read response."""
        line = json.dumps(msg) + "\n"
        proc.stdin.write(line.encode("utf-8"))
        proc.stdin.flush()

        if not expect_response:
            return None

        deadline = time.time() + 30
        while time.time() < deadline:
            r, _, _ = select.select([proc.stdout], [], [], 0.5)
            if r:
                resp = proc.stdout.readline()
                if resp:
                    return json.loads(resp.decode("utf-8"))
        return {"error": "timeout", "message": "No response from child server within 30s"}

    def list_all_tools(self) -> list[dict]:
        """Aggregate tools from all connected services with janus_ prefix."""
        aggregated = []
        with _children_lock:
            for key, child in list(_children.items()):
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

        with _children_lock:
            child = _children.get(service_key)

        if not child:
            return {"isError": True, "content": [{"type": "text", "text": f"Service '{service_key}' is not connected. Run `janus connect {service_key}` first."}]}

        if child.get("error"):
            return {"isError": True, "content": [{"type": "text", "text": f"Service '{service_key}' error: {child['error']}"}]}

        try:
            result = self._send_sync(child["proc"], {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": child_tool_name, "arguments": arguments},
            })
            return result or {"isError": True, "content": [{"type": "text", "text": "No response from child server"}]}
        except Exception as e:
            logger.error("Tool call failed for %s/%s: %s", service_key, child_tool_name, e)
            return {"isError": True, "content": [{"type": "text", "text": str(e)}]}

    def stop_all(self):
        """Terminate all child server processes."""
        with _children_lock:
            for key, child in list(_children.items()):
                if "proc" in child:
                    try:
                        child["proc"].terminate()
                    except Exception:
                        pass
            _children.clear()

    def get_status(self) -> list[dict]:
        """Get status of all services."""
        statuses = []
        with _children_lock:
            for key, child in list(_children.items()):
                statuses.append({
                    "key": key,
                    "name": child.get("definition", {}).get("name", key),
                    "connected": "proc" in child and child["proc"].poll() is None,
                    "tools": len(child.get("tools", [])),
                    "error": child.get("error"),
                })
        return statuses
