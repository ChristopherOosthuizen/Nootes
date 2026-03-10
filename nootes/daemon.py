"""Background daemon management with PID file."""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path

from nootes.categories import CategoriesManager
from nootes.categorizer import Categorizer
from nootes.config import NootesConfig
from nootes.git_ops import GitOps
from nootes.organizer import Organizer
from nootes.watcher import create_observer

logger = logging.getLogger("nootes.daemon")


def _write_pid(pid_file: Path) -> None:
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()), encoding="utf-8")


def _read_pid(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def is_running(config: NootesConfig) -> bool:
    pid = _read_pid(config.pid_file)
    if pid is None:
        return False
    return _is_process_alive(pid)


def start_daemon(config: NootesConfig) -> None:
    """Start the background watcher daemon via double-fork."""
    if is_running(config):
        pid = _read_pid(config.pid_file)
        print(f"nootes daemon is already running (PID {pid}).")
        sys.exit(1)

    # Double-fork to fully daemonize
    pid = os.fork()
    if pid > 0:
        # Parent: wait briefly then exit
        time.sleep(0.5)
        print(f"nootes daemon started (PID {pid}).")
        return

    # First child: create new session
    os.setsid()

    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)

    # Grandchild: the actual daemon
    _run_daemon_loop(config)


def _run_daemon_loop(config: NootesConfig) -> None:
    """The main daemon loop running in the background."""
    # Set up logging to file
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(config.log_file),
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Redirect stdout/stderr to log file
    log_fd = open(config.log_file, "a")  # noqa: SIM115
    os.dup2(log_fd.fileno(), sys.stdout.fileno())
    os.dup2(log_fd.fileno(), sys.stderr.fileno())

    # Write PID file
    _write_pid(config.pid_file)

    # Signal handling for graceful shutdown
    shutdown_requested = False

    def handle_signal(signum: int, frame: object) -> None:
        nonlocal shutdown_requested
        shutdown_requested = True
        logger.info("Received signal %d, shutting down...", signum)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Initialize components
    categories_mgr = CategoriesManager(config.categories_file)
    categorizer = Categorizer(config, categories_mgr)
    git_ops = GitOps(config)
    organizer = Organizer(config, categories_mgr, categorizer, git_ops)

    # Start watchdog observer
    observer = create_observer(organizer, config.watch_dir)
    observer.start()
    logger.info("Daemon started, watching: %s", config.watch_dir)

    try:
        while not shutdown_requested:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        config.pid_file.unlink(missing_ok=True)
        log_fd.close()
        logger.info("Daemon stopped.")


def stop_daemon(config: NootesConfig) -> None:
    """Stop the running daemon by sending SIGTERM."""
    pid = _read_pid(config.pid_file)
    if pid is None:
        print("nootes daemon is not running (no PID file found).")
        return

    if not _is_process_alive(pid):
        print(f"nootes daemon is not running (stale PID {pid}).")
        config.pid_file.unlink(missing_ok=True)
        return

    print(f"Stopping nootes daemon (PID {pid})...")
    os.kill(pid, signal.SIGTERM)

    for _ in range(30):
        time.sleep(1)
        if not _is_process_alive(pid):
            print("nootes daemon stopped.")
            config.pid_file.unlink(missing_ok=True)
            return

    print(f"Warning: daemon (PID {pid}) did not stop within 30 seconds.")
