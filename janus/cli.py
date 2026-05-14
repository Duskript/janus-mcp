"""Janus CLI — self-hosted MCP connector hub."""

import sys
import click


@click.group()
@click.version_option(prog_name="janus-mcp")
def main():
    """Janus — self-hosted MCP connector hub.

    Aggregate, manage, and authenticate MCP servers under one namespace.
    """
    pass


@main.command()
@click.argument("query", required=False, default="")
def search(query):
    """Search available services from the Janus registry."""
    from .registry import registry_search
    results = registry_search(query)
    if not results:
        click.echo("No services found. Try `janus update` to refresh the registry.")
        return
    click.echo(f"{'Service':<20} {'Category':<18} {'Auth':<10}")
    click.echo("-" * 50)
    for svc in results:
        click.echo(f"{svc['name']:<20} {svc.get('category', '-'):<18} {svc.get('auth', {}).get('type', '-'):<10}")


@main.command()
@click.argument("service_key")
def info(service_key):
    """Show full definition for a service."""
    from .registry import registry_get
    svc = registry_get(service_key)
    if not svc:
        click.echo(f"Service '{service_key}' not found in registry.")
        sys.exit(1)
    click.echo(f"Name:        {svc['name']}")
    click.echo(f"Package:     {svc.get('package', '-')}")
    click.echo(f"Runner:      {svc.get('runner', '-')}")
    click.echo(f"Auth type:   {svc.get('auth', {}).get('type', 'none')}")
    click.echo(f"Setup URL:   {svc.get('auth', {}).get('setup_url', '-')}")
    click.echo(f"Category:    {svc.get('category', '-')}")
    click.echo(f"Description: {svc.get('description', '')}")
    hint = svc.get('auth', {}).get('setup_hint', '')
    if hint:
        click.echo(f"\nSetup hint: {hint}")


@main.command()
@click.argument("service_key")
def install(service_key):
    """Download a service definition from the registry."""
    from .registry import registry_install
    path = registry_install(service_key)
    if path:
        click.echo(f"Installed '{service_key}' → {path}")
        click.echo(f"Run `janus connect {service_key}` to authenticate.")
    else:
        click.echo(f"Failed to install '{service_key}'. Is it in the registry?")
        sys.exit(1)


@main.command()
@click.argument("service_key")
@click.option("--api-key", help="API key or PAT for authentication")
def connect(service_key, api_key):
    """Authenticate and enable a service."""
    from .vault import vault_store
    from .registry import registry_get

    svc = registry_get(service_key)
    if not svc:
        click.echo(f"Service '{service_key}' not found. Install it first with `janus install {service_key}`.")
        sys.exit(1)

    auth_type = svc.get("auth", {}).get("type", "none")

    if auth_type == "none":
        vault_store(service_key, {"type": "none"})
        click.echo(f"Connected '{service_key}' (no auth required).")

    elif auth_type in ("pat", "apikey"):
        if not api_key:
            api_key = click.prompt(f"Paste your {auth_type.upper()} for {service_key}", hide_input=True)
        vault_store(service_key, {"type": auth_type, "token": api_key})
        click.echo(f"✓ Connected '{service_key}'.")

    elif auth_type == "oauth":
        click.echo(f"OAuth flow not yet implemented for '{service_key}'.")
        click.echo(f"Set up credentials manually at: {svc.get('auth', {}).get('setup_url', '?')}")
        sys.exit(1)

    else:
        click.echo(f"Unknown auth type '{auth_type}' for '{service_key}'.")
        sys.exit(1)


@main.command()
@click.argument("service_key")
def remove(service_key):
    """Disconnect and remove a service."""
    from .vault import vault_remove
    import shutil
    from pathlib import Path

    config_dir = Path.home() / ".config" / "janus" / "services.d"
    svc_file = config_dir / f"{service_key}.yaml"
    if svc_file.exists():
        svc_file.unlink()
    vault_remove(service_key)
    click.echo(f"✓ Removed '{service_key}'.")


@main.command("list")
def list_services():
    """List all installed services and their status."""
    from pathlib import Path
    from .registry import registry_get_all_local

    services = registry_get_all_local()
    if not services:
        click.echo("No services installed. Run `janus search` to find services, then `janus install <name>`.")
        return

    from .vault import vault_has
    click.echo(f"{'Service':<20} {'Status':<12}")
    click.echo("-" * 32)
    for svc in services:
        key = svc.get("key", "?")
        connected = "✓ connected" if vault_has(key) else "✗ not authed"
        click.echo(f"{key:<20} {connected}")


@main.command()
def update():
    """Pull the latest registry INDEX.md."""
    from .registry import registry_update
    count = registry_update()
    click.echo(f"Registry updated. {count} services available.")


@main.command()
def serve():
    """Start the MCP aggregator server (stdio mode)."""
    from .server import run_server
    run_server()


@main.command()
@click.option("--port", default=8011, help="HTTP SSE port (default: 8011)")
def start(port):
    """Start Janus as an HTTP SSE server."""
    from .server import run_http_server
    run_http_server(port=port)


@main.group()
def vault():
    """Manage the encrypted token vault."""
    pass


@vault.command("init")
def vault_init():
    """Initialize/rekey the encrypted vault."""
    from .vault import vault_init
    vault_init()
    click.echo("✓ Vault initialized.")


@vault.command("update")
@click.argument("key")
@click.argument("value")
def vault_update(key, value):
    """Store a value in the vault."""
    from .vault import vault_store
    vault_store(key, {"type": "raw", "value": value})
    click.echo(f"✓ Stored '{key}' in vault.")
