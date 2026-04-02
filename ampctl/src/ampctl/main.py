"""CLI entry point for ampctl – Amplifier agent management."""

from __future__ import annotations

import shutil
from pathlib import Path

import click
import httpx

from ampctl.compose import generate_compose, write_compose
from ampctl.parser import fetch_definition
from ampctl.paths import agents_dir, service_map_path
from ampctl.service_map import (
    build_service_map_entry,
    load_service_map,
    save_service_map,
)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
def main() -> None:
    """ampctl – Amplifier agent management CLI."""


# ---------------------------------------------------------------------------
# add
# ---------------------------------------------------------------------------


@main.command()
@click.argument("uri")
@click.argument("name")
@click.option(
    "--force", is_flag=True, default=False, help="Overwrite if already installed."
)
def add(uri: str, name: str, force: bool) -> None:
    """Fetch an agent definition from URI and install it as NAME."""
    # Step 1 – validate YAML
    try:
        agent = fetch_definition(uri)
    except FileNotFoundError as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(f"Invalid agent definition: {exc}") from exc

    # Step 2 – check for existing installation
    dest = agents_dir() / f"{name}.yaml"
    if dest.exists() and not force:
        raise click.ClickException(
            f"Agent '{name}' already exists. Use --force to overwrite."
        )

    # Step 3 – write YAML to agents dir
    agents_dir().mkdir(parents=True, exist_ok=True)
    if uri.startswith("https://"):
        response = httpx.get(uri)
        response.raise_for_status()
        dest.write_text(response.text)
    else:
        shutil.copy2(Path(uri).expanduser().resolve(), dest)

    # Step 4 – update service map
    sm = load_service_map(service_map_path())
    sm.agents[name] = build_service_map_entry(agent)
    save_service_map(sm, service_map_path())

    svc_count = sum(1 for _ in agent.all_service_entries())
    click.echo(
        click.style("Added", fg="green")
        + f" agent {click.style(name, bold=True)}"
        + f" (ref: {agent.ref}, {svc_count} services)"
    )


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def remove(name: str) -> None:
    """Remove an installed agent by NAME."""
    dest = agents_dir() / f"{name}.yaml"
    if not dest.exists():
        raise click.ClickException(f"Agent '{name}' not found.")

    dest.unlink()

    sm = load_service_map(service_map_path())
    sm.agents.pop(name, None)
    save_service_map(sm, service_map_path())

    click.echo(
        click.style("Removed", fg="yellow") + f" agent {click.style(name, bold=True)}."
    )


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------


@main.command(name="list")
def list_agents() -> None:
    """List all installed agents."""
    adir = agents_dir()
    if not adir.exists():
        click.echo("No agents installed.")
        return

    files = sorted(adir.glob("*.yaml"))
    if not files:
        click.echo("No agents installed.")
        return

    # Print a simple text table – works in every terminal and in tests
    header = f"{'Name':<24} {'Ref':<34} {'Description':<38} {'Svcs':>4}"
    click.echo(header)
    click.echo("-" * len(header))

    for f in files:
        agent_name = f.stem
        try:
            agent = fetch_definition(str(f))
            desc = (agent.description or "")[:36]
            svc_count = sum(1 for _ in agent.all_service_entries())
            click.echo(f"{agent_name:<24} {agent.ref:<34} {desc:<38} {svc_count:>4}")
        except Exception as exc:  # noqa: BLE001
            click.echo(f"{agent_name:<24} {'(error)':<34} {str(exc)[:36]:<38} {'?':>4}")


# ---------------------------------------------------------------------------
# compose
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--output",
    default="docker-compose.yaml",
    show_default=True,
    type=click.Path(),
    help="Output file path.",
)
def compose(output: str) -> None:
    """Generate a docker-compose.yaml from all installed agents."""
    adir = agents_dir()
    sm = load_service_map(service_map_path())

    agents: dict[str, tuple] = {}
    if adir.exists():
        for f in sorted(adir.glob("*.yaml")):
            agent_name = f.stem
            try:
                agent = fetch_definition(str(f))
            except Exception as exc:  # noqa: BLE001
                raise click.ClickException(
                    f"Failed to load '{agent_name}': {exc}"
                ) from exc

            # Use stored service map entry or derive one on the fly
            sme = sm.agents.get(agent_name) or build_service_map_entry(agent)
            agents[agent.ref] = (agent, sme)

    result = generate_compose(agents)
    output_path = Path(output)
    write_compose(result, output_path)

    svc_count = len(result.get("services", {}))
    click.echo(
        click.style("Generated", fg="green")
        + f" {click.style(str(output_path), bold=True)}"
        + f" ({svc_count} services)"
    )


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


@main.command()
@click.argument("name")
def inspect(name: str) -> None:
    """Show details of an installed agent by NAME."""
    agent_file = agents_dir() / f"{name}.yaml"
    if not agent_file.exists():
        raise click.ClickException(f"Agent '{name}' not found.")

    try:
        agent = fetch_definition(str(agent_file))
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Failed to load agent: {exc}") from exc

    sm = load_service_map(service_map_path())
    sme = sm.agents.get(name)

    click.echo(f"Ref:         {agent.ref}")
    click.echo(f"Description: {agent.description or '(none)'}")

    if agent.instruction:
        instr = agent.instruction
        truncated = instr[:80] + "..." if len(instr) > 80 else instr
        click.echo(f"Instruction: {truncated}")

    click.echo("")
    col_header = f"{'Role':<20} {'App-ID':<42} {'Image / Build'}"
    click.echo(col_header)
    click.echo("-" * max(len(col_header), 80))

    for role_key, service_entry in agent.all_service_entries():
        if sme is None:
            app_id = "(unknown)"
        elif role_key == "orchestrator":
            app_id = sme.orchestrator
        elif role_key == "context_manager":
            app_id = sme.context_manager
        elif role_key == "providers":
            app_id = sme.providers
        else:
            app_id = sme.behaviors.get(role_key, "(unknown)")

        image_or_build = service_entry.image or str(service_entry.build)
        click.echo(f"{role_key:<20} {app_id:<42} {image_or_build}")
