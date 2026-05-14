"""Janus Proxy — Route tool calls to child MCP servers."""

import logging

logger = logging.getLogger(__name__)


def proxy_list_tools(services: dict) -> list[dict]:
    """Aggregate tools from all connected child servers with janus_ prefix."""
    tools = []
    for service_key, child in services.items():
        if not child.get("tools"):
            continue
        for tool in child["tools"]:
            prefixed = {
                "name": f"janus_{service_key}_{tool['name']}",
                "description": tool.get("description", ""),
                "inputSchema": tool.get("inputSchema", {}),
                "_janus_service": service_key,
                "_janus_tool": tool["name"],
            }
            tools.append(prefixed)
    return tools


def proxy_call_tool(services: dict, name: str, arguments: dict) -> dict:
    """Route a tool call to the correct child server."""
    # Parse janus_{service_key}_{tool_name}
    if not name.startswith("janus_"):
        return {"error": f"Unknown tool: {name}"}

    parts = name.split("_", 2)
    if len(parts) < 3:
        return {"error": f"Invalid tool name format: {name}"}

    service_key = parts[1]
    child_tool_name = parts[2]

    child = services.get(service_key)
    if not child:
        return {"error": f"Service '{service_key}' is not connected."}

    if child.get("error"):
        return {"error": child["error"]}

    # Forward call to child server
    try:
        result = child["client"].call_tool(child_tool_name, arguments)
        return {"result": result}
    except Exception as e:
        logger.error("Tool call failed for %s/%s: %s", service_key, child_tool_name, e)
        return {"error": str(e)}
