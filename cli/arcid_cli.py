"""arcid — CLI for the ArcID agent identity registry.

Commands
--------
  arcid health                          — liveness check
  arcid config                          — resolved addresses and mode flags
  arcid register --name "..."           — register a new agent
  arcid agents list                     — paginated leaderboard
  arcid agents inspect <agent_id>       — full record for one agent
  arcid agents fees <agent_id>          — USDC builder fees earned
  arcid agents decide <agent_id>        — run a sentiment decision cycle
  arcid agents order <agent_id>         — place an attributed Polymarket order

Global flags (before any sub-command)
--------------------------------------
  --endpoint  ArcID backend URL  (default: http://localhost:8000)
  --json      Print raw JSON instead of formatted output
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any, List, Optional

import httpx
import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# App scaffolding
# ---------------------------------------------------------------------------

app = typer.Typer(
    name="arcid",
    help="ArcID — hardware-backed agent identity on Arc.",
    no_args_is_help=True,
    add_completion=False,
)
agents_app = typer.Typer(help="Manage registered agents.", no_args_is_help=True)
app.add_typer(agents_app, name="agents")

console = Console()

_DEFAULT_ENDPOINT = "http://localhost:8000"


# Typer doesn't support a true global context that sub-apps inherit cleanly,
# so we store the endpoint in a module-level variable set by the root callback.
_endpoint: str = _DEFAULT_ENDPOINT
_raw_json: bool = False


@app.callback()
def root(
    endpoint: str = typer.Option(
        _DEFAULT_ENDPOINT, "--endpoint", "-e", help="ArcID backend base URL.", show_default=True
    ),
    raw: bool = typer.Option(False, "--json", help="Print raw JSON output."),
) -> None:
    global _endpoint, _raw_json
    _endpoint = endpoint.rstrip("/")
    _raw_json = raw


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(path: str, params: dict | None = None) -> Any:
    url = f"{_endpoint}{path}"
    try:
        r = httpx.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to {_endpoint}. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}:[/red] {e.response.text}")
        raise typer.Exit(1)


def _post(path: str, body: dict) -> Any:
    url = f"{_endpoint}{path}"
    try:
        r = httpx.post(url, json=body, timeout=60)
        r.raise_for_status()
        return r.json()
    except httpx.ConnectError:
        console.print(f"[red]Cannot connect to {_endpoint}. Is the backend running?[/red]")
        raise typer.Exit(1)
    except httpx.HTTPStatusError as e:
        console.print(f"[red]HTTP {e.response.status_code}:[/red] {e.response.text}")
        raise typer.Exit(1)


def _dump(data: Any) -> None:
    """Print raw JSON if --json was passed, otherwise let the caller format."""
    if _raw_json:
        console.print_json(json.dumps(data))
        raise typer.Exit(0)


def _short(hex_str: str, chars: int = 10) -> str:
    if len(hex_str) <= chars * 2 + 2:
        return hex_str
    return hex_str[:chars] + "…" + hex_str[-6:]


def _resolve_agent_id(partial: str) -> str:
    """Accept a full or prefix agent ID and return the full 66-char hex ID.

    Lets users paste the truncated leaderboard display (e.g. '0x532624') instead
    of the full bytes32 ID. Fetches /agents and matches on prefix.
    """
    clean = partial.replace("…", "").replace(".", "")  # strip display artifacts
    if len(clean) == 66:  # already full
        return clean
    agents = _get("/agents", params={"offset": 0, "limit": 200}).get("agents", [])
    matches = [a["agent_id"] for a in agents if a["agent_id"].startswith(clean)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        console.print(f"[yellow]Prefix '{clean}' matches {len(matches)} agents — be more specific:[/yellow]")
        for m in matches:
            console.print(f"  {m}")
        raise typer.Exit(1)
    console.print(f"[red]No agent found with ID starting '{clean}'. Run 'arcid agents list' to see IDs.[/red]")
    raise typer.Exit(1)


def _ts(epoch: int) -> str:
    if not epoch:
        return "—"
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ---------------------------------------------------------------------------
# arcid health
# ---------------------------------------------------------------------------

@app.command()
def health() -> None:
    """Check that the backend is reachable."""
    data = _get("/health")
    _dump(data)
    status = data.get("status", "unknown")
    color = "green" if status == "ok" else "red"
    console.print(Panel(f"[{color}]{status}[/{color}]", title="ArcID health", expand=False))


# ---------------------------------------------------------------------------
# arcid config
# ---------------------------------------------------------------------------

@app.command("config")
def show_config() -> None:
    """Show resolved contract addresses and integration mode flags."""
    data = _get("/config")
    _dump(data)

    addrs = data.get("addresses", {})
    modes = data.get("modes", {})

    addr_table = Table(show_header=True, header_style="bold cyan", box=None)
    addr_table.add_column("Contract", style="dim")
    addr_table.add_column("Address")
    for name, addr in addrs.items():
        addr_table.add_row(name, addr or "[dim]not set[/dim]")

    mode_table = Table(show_header=True, header_style="bold cyan", box=None)
    mode_table.add_column("Mode")
    mode_table.add_column("Value")
    for k, v in modes.items():
        color = "yellow" if v else "green"
        mode_table.add_row(k, f"[{color}]{v}[/{color}]")

    console.print(Panel(addr_table, title="Contract addresses", expand=False))
    console.print(Panel(mode_table, title="Integration modes", expand=False))
    console.print(f"  [dim]Arc RPC:[/dim] {data.get('arc_rpc_url')}  "
                  f"[dim]chain:[/dim] {data.get('arc_chain_id')}")


# ---------------------------------------------------------------------------
# arcid register
# ---------------------------------------------------------------------------

@app.command()
def register(
    name: str = typer.Option(..., "--name", "-n", help="Human-readable agent name (max 64 chars)."),
    key: Optional[str] = typer.Option(None, "--key", help="Pre-generated agent private key (hex). Generated automatically if omitted."),
) -> None:
    """Register a new agent. Generates a DCAP attestation and anchors the agent on Arc."""
    body: dict = {"name": name}
    if key:
        body["agent_private_key"] = key

    console.print(f"[dim]Registering agent [bold]{name}[/bold] via {_endpoint} ...[/dim]")
    data = _post("/register", body)
    _dump(data)

    sponsored = data.get("gas_sponsored", False)
    sponsor_label = "[green]yes — gas sponsored[/green]" if sponsored else "[yellow]no — fee paid[/yellow]"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Agent ID",      f"[bold cyan]{data['agent_id']}[/bold cyan]")
    grid.add_row("Name",          data["name"])
    grid.add_row("Signer",        _short(data["attested_signer"]))
    grid.add_row("MRTD",          _short(data["mrtd_hex"]))
    grid.add_row("Wallet",        data["wallet_address"])
    grid.add_row("Register tx",   data["tx_hash"])
    if data.get("bind_tx_hash"):
        grid.add_row("Bind tx",   data["bind_tx_hash"])
    grid.add_row("Gas sponsored", sponsor_label)

    console.print(Panel(grid, title=f"[bold green]Agent registered[/bold green]", expand=False))
    console.print("\n[dim]Save your Agent ID — you'll need it for orders and decisions:[/dim]")
    console.print(f"  [bold]{data['agent_id']}[/bold]\n")


# ---------------------------------------------------------------------------
# arcid agents list
# ---------------------------------------------------------------------------

@agents_app.command("list")
def agents_list(
    offset: int = typer.Option(0, "--offset", help="Pagination offset."),
    limit: int = typer.Option(20, "--limit", "-l", help="Number of agents to show."),
) -> None:
    """Print the leaderboard of registered agents."""
    data = _get("/agents", params={"offset": offset, "limit": limit})
    _dump(data)

    agents = data.get("agents", [])
    total = data.get("total", len(agents))

    if not agents:
        console.print("[dim]No agents registered yet.[/dim]")
        return

    table = Table(
        title=f"ArcID Leaderboard  ({total} agents)",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Name", min_width=16)
    table.add_column("Agent ID", style="cyan")
    table.add_column("Wallet", style="dim")
    table.add_column("Fees (USDC)", justify="right")
    table.add_column("Registered", style="dim")
    table.add_column("TEE", justify="center")

    for i, a in enumerate(agents, start=offset + 1):
        fees = a.get("builder_fees_usdc", 0.0)
        fees_str = f"${fees:.4f}" if fees else "—"
        tee = "[green]✓[/green]" if a.get("mrtd") and a["mrtd"] != "0x" + "0" * 64 else "[dim]—[/dim]"
        table.add_row(
            str(i),
            a.get("name", "—"),
            _short(a["agent_id"], 8),
            _short(a.get("attested_signer", "—"), 6),
            fees_str,
            _ts(a.get("registered_at", 0)),
            tee,
        )

    console.print(table)


# ---------------------------------------------------------------------------
# arcid agents inspect
# ---------------------------------------------------------------------------

@agents_app.command("inspect")
def agents_inspect(
    agent_id: str = typer.Argument(..., help="Full or prefix agent ID (e.g. 0x532624)."),
) -> None:
    """Show the full on-chain record for a single agent."""
    agent_id = _resolve_agent_id(agent_id)
    data = _get(f"/agents/{agent_id}")
    _dump(data)

    fees = data.get("builder_fees_usdc", 0.0)
    tee_ok = data.get("mrtd") and data["mrtd"] != "0x" + "0" * 64

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Agent ID",      f"[bold cyan]{data['agent_id']}[/bold cyan]")
    grid.add_row("Name",          data.get("name", "—"))
    grid.add_row("Attested signer", data.get("attested_signer", "—"))
    grid.add_row("MRTD",          data.get("mrtd", "—"))
    grid.add_row("Report data",   _short(data.get("report_data", "—")))
    grid.add_row("Wallet",        data.get("wallet", "—"))
    grid.add_row("Fees earned",   f"${fees:.6f} USDC")
    grid.add_row("TEE verified",  "[green]YES[/green]" if tee_ok else "[yellow]prototype / mock[/yellow]")
    grid.add_row("Registered at", _ts(data.get("registered_at", 0)))
    grid.add_row("Gas sponsored", str(data.get("gas_sponsored", False)))

    console.print(Panel(grid, title=f"[bold]{data.get('name', agent_id)}[/bold]", expand=False))


# ---------------------------------------------------------------------------
# arcid agents fees
# ---------------------------------------------------------------------------

@agents_app.command("fees")
def agents_fees(
    agent_id: str = typer.Argument(..., help="Full or prefix agent ID (e.g. 0x532624)."),
) -> None:
    """Show cumulative USDC builder fees earned by an agent."""
    agent_id = _resolve_agent_id(agent_id)
    data = _get(f"/agents/{agent_id}/fees")
    _dump(data)
    fees = data.get("builder_fees_usdc", 0.0)
    console.print(f"  [bold cyan]{_short(agent_id)}[/bold cyan] has earned [bold green]${fees:.6f} USDC[/bold green] in builder fees.")


# ---------------------------------------------------------------------------
# arcid agents decide
# ---------------------------------------------------------------------------

@agents_app.command("decide")
def agents_decide(
    agent_id: str = typer.Argument(..., help="Full or prefix agent ID (e.g. 0x532624)."),
    market: str = typer.Option(..., "--market", "-m", help="Prediction market question."),
    signal: Optional[List[str]] = typer.Option(None, "--signal", "-s", help="Sentiment signal (repeatable)."),
) -> None:
    """Run a sentiment decision cycle for a registered agent.

    Example:

        arcid agents decide 0xabc... \\
            --market "Will ETH hit $5k by EOY?" \\
            --signal "Strong ETF inflows this week" \\
            --signal "Fed pivot expected Q3"
    """
    agent_id = _resolve_agent_id(agent_id)
    body = {
        "market_question": market,
        "signals": list(signal) if signal else [],
    }
    data = _post(f"/agents/{agent_id}/decide", body)
    _dump(data)

    side = data.get("side", "?")
    conf = float(data.get("confidence", 0.0))
    conf_pct = int(conf * 100)
    size = data.get("suggested_size_usdc", 0.0)
    rationale = data.get("rationale", "")

    side_color = "green" if side == "YES" else "red"
    trade = size > 0

    bar_filled = int(conf_pct / 5)
    bar = "[" + "█" * bar_filled + "░" * (20 - bar_filled) + f"] {conf_pct}%"

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Market",      market)
    grid.add_row("Decision",    f"[bold {side_color}]{side}[/bold {side_color}]")
    grid.add_row("Confidence",  bar)
    grid.add_row("Size",        f"${size:.2f} USDC" if trade else "[dim]no trade (confidence too low)[/dim]")
    grid.add_row("Rationale",   rationale or "[dim]—[/dim]")

    title_color = side_color if trade else "yellow"
    title = f"[bold {title_color}]{'TRADE' if trade else 'HOLD'}[/bold {title_color}]"
    console.print(Panel(grid, title=title, expand=False))


# ---------------------------------------------------------------------------
# arcid agents order
# ---------------------------------------------------------------------------

@agents_app.command("order")
def agents_order(
    agent_id: str = typer.Argument(..., help="Full or prefix agent ID (e.g. 0x532624)."),
    market: str = typer.Option(..., "--market", "-m", help="Prediction market question."),
    side: str = typer.Option(..., "--side", help="YES or NO."),
    size: float = typer.Option(..., "--size", help="Order size in USDC (max 100)."),
) -> None:
    """Place an attributed Polymarket order carrying this agent's ArcID as the builder code.

    Example:

        arcid agents order 0xabc... \\
            --market "Will BTC hit $100k?" \\
            --side YES \\
            --size 2.50
    """
    agent_id = _resolve_agent_id(agent_id)
    side = side.upper()
    if side not in ("YES", "NO"):
        console.print("[red]--side must be YES or NO[/red]")
        raise typer.Exit(1)
    if size <= 0 or size > 100:
        console.print("[red]--size must be between 0 and 100 USDC[/red]")
        raise typer.Exit(1)

    body = {"market_question": market, "side": side, "size_usdc": size}
    console.print(f"[dim]Placing {side} order for ${size:.2f} USDC ...[/dim]")
    data = _post(f"/agents/{agent_id}/order", body)
    _dump(data)

    side_color = "green" if data.get("side") == "YES" else "red"
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim")
    grid.add_column()
    grid.add_row("Market",       data.get("market_question", market))
    grid.add_row("Side",         f"[bold {side_color}]{data.get('side')}[/bold {side_color}]")
    grid.add_row("Size",         f"${data.get('size_usdc', size):.2f} USDC")
    grid.add_row("Fill price",   str(data.get("fill_price", "—")))
    grid.add_row("Builder fee",  f"${data.get('builder_fee_usdc', 0.0):.6f} USDC")
    grid.add_row("Builder code", data.get("builder_code", agent_id))
    grid.add_row("Tx hash",      data.get("tx_hash", "—"))
    grid.add_row("Venue",        data.get("venue", "Polymarket"))

    console.print(Panel(grid, title="[bold green]Order placed[/bold green]", expand=False))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app()
