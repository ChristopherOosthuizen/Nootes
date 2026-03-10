"""Watchdog filesystem watcher for new/changed files."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from nootes.organizer import Organizer
from nootes.readers import is_supported

logger = logging.getLogger("nootes.watcher")

DEBOUNCE_SECONDS = 2.0


class NootesEventHandler(FileSystemEventHandler):
    """Handles filesystem events in the watched directory."""

    def __init__(self, organizer: Organizer, watch_dir: Path) -> None:
        super().__init__()
        self._organizer = organizer
        self._watch_dir = watch_dir
        self._pending: dict[str, float] = {}

    def _should_process(self, path: Path) -> bool:
        try:
            relative = path.relative_to(self._watch_dir)
        except ValueError:
            return False

        # Only process files in the root of watch_dir
        if len(relative.parts) != 1:
            return False

        if path.name.startswith("."):
            return False

        if not is_supported(path):
            return False

        return True

    def on_created(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_process(path):
            self._schedule(path)

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if self._should_process(path):
            self._schedule(path)

    def _schedule(self, path: Path) -> None:
        """Schedule a file for processing with debounce."""
        now = time.time()
        key = str(path)
        last = self._pending.get(key, 0.0)
        if now - last < DEBOUNCE_SECONDS:
            return

        self._pending[key] = now
        logger.info("Queued for processing: %s", path.name)

        threading.Timer(
            DEBOUNCE_SECONDS,
            self._process_safely,
            args=(path,),
        ).start()

    def _process_safely(self, path: Path) -> None:
        try:
            self._organizer.process_file(path)
        except Exception:
            logger.exception("Error processing %s", path.name)


def create_observer(organizer: Organizer, watch_dir: Path) -> Observer:
    """Create and configure a watchdog Observer."""
    handler = NootesEventHandler(organizer, watch_dir)
    observer = Observer()
    observer.schedule(handler, str(watch_dir), recursive=False)
    return observer
