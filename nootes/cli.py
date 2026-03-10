"""Click CLI entry points for nootes."""

from __future__ import annotations

import json
import logging
import sys

import click

from nootes.config import load_config


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose output.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """nootes - AI-powered notes organizer."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.option(
    "--dir",
    "-d",
    "directory",
    type=click.Path(),
    help="Directory to initialize. Defaults to NOOTES_WATCH_DIR from .env.",
)
def init(directory: str | None) -> None:
    """Initialize a new nootes-managed folder."""
    from pathlib import Path

    from nootes.config import NootesConfig
    from nootes.git_ops import GitOps

    if directory:
        watch_dir = Path(directory).expanduser().resolve()
        import os

        from dotenv import load_dotenv

        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY", "placeholder")
        config = NootesConfig(
            watch_dir=watch_dir,
            openai_api_key=api_key,
            github_repo=os.getenv("GITHUB_REPO"),
        )
    else:
        config = load_config()

    # Create watch directory if it doesn't exist
    config.watch_dir.mkdir(parents=True, exist_ok=True)

    # Create .nootes directory
    config.nootes_dir.mkdir(parents=True, exist_ok=True)

    # Create initial categories.json
    if not config.categories_file.exists():
        config.categories_file.write_text(
            json.dumps({"version": 1, "categories": {}}, indent=2),
            encoding="utf-8",
        )

    # Create .gitignore in .nootes to exclude runtime files
    gitignore = config.nootes_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("nootes.pid\nnootes.log\n", encoding="utf-8")

    # Initialize git repo
    git_ops = GitOps(config)
    try:
        git_ops.init_repo()
        click.echo(f"Initialized git repo at {config.watch_dir}")
    except Exception:
        click.echo("Git repo already exists.")

    # Create private GitHub repo if GITHUB_REPO is configured
    if config.github_repo:
        click.echo(f"Creating private GitHub repo: {config.github_repo}...")
        git_ops.create_private_remote(config.github_repo)

    click.echo(f"Initialized nootes in: {config.watch_dir}")
    click.echo(f"  Categories file: {config.categories_file}")
    click.echo(f"  Add your notes to: {config.watch_dir}")


@cli.command()
def watch() -> None:
    """Start the background daemon watching the folder."""
    config = load_config()
    if not config.nootes_dir.exists():
        click.echo("Error: nootes not initialized. Run 'nootes init' first.")
        sys.exit(1)

    from nootes.daemon import start_daemon

    start_daemon(config)


@cli.command()
def stop() -> None:
    """Stop the background daemon."""
    config = load_config()

    from nootes.daemon import stop_daemon

    stop_daemon(config)


@cli.command()
def sort() -> None:
    """One-time sort of all files in the watched folder."""
    config = load_config()
    if not config.nootes_dir.exists():
        click.echo("Error: nootes not initialized. Run 'nootes init' first.")
        sys.exit(1)

    from nootes.categories import CategoriesManager
    from nootes.categorizer import Categorizer
    from nootes.git_ops import GitOps
    from nootes.organizer import Organizer

    categories_mgr = CategoriesManager(config.categories_file)
    categorizer = Categorizer(config, categories_mgr)
    git_ops = GitOps(config)
    organizer = Organizer(config, categories_mgr, categorizer, git_ops)

    click.echo(f"Sorting files in: {config.watch_dir}")
    count = organizer.sort_all()
    click.echo(f"Done. Processed {count} files.")


@cli.command("full-categorize")
def full_categorize_cmd() -> None:
    """Map-reduce: rebuild categories from scratch and re-sort everything."""
    config = load_config()
    if not config.nootes_dir.exists():
        click.echo("Error: nootes not initialized. Run 'nootes init' first.")
        sys.exit(1)

    from nootes.full_categorize import full_categorize

    count = full_categorize(config, on_progress=click.echo)
    click.echo(f"Done. Re-categorized {count} files.")


@cli.command()
def status() -> None:
    """Show current categories and file counts."""
    config = load_config()
    if not config.nootes_dir.exists():
        click.echo("Error: nootes not initialized. Run 'nootes init' first.")
        sys.exit(1)

    from nootes.categories import CategoriesManager
    from nootes.daemon import is_running

    categories_mgr = CategoriesManager(config.categories_file)
    categories = categories_mgr.get_all()
    counts = categories_mgr.file_count_by_category(config.watch_dir)

    daemon_status = "running" if is_running(config) else "stopped"
    click.echo(f"Daemon: {daemon_status}")
    click.echo(f"Watch directory: {config.watch_dir}")
    click.echo()

    if not categories:
        click.echo("No categories yet. Add some notes and run 'nootes sort'.")
        return

    click.echo(f"Categories ({len(categories)}):")
    for cat_name, cat in sorted(categories.items()):
        file_count = counts.get(cat_name, 0)
        click.echo(f"  {cat_name} ({file_count} files): {cat.description}")
        for sub_name, sub in sorted(cat.subcategories.items()):
            click.echo(f"    - {sub_name}: {sub.description}")
