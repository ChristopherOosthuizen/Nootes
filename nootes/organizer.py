"""File moving and organizing logic."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from nootes.categories import CategoriesManager
from nootes.categorizer import Categorizer, CategorizationResult
from nootes.config import NootesConfig
from nootes.git_ops import GitOps
from nootes.readers import extract_content, is_supported

logger = logging.getLogger("nootes.organizer")


class Organizer:
    """Orchestrates: read file -> categorize -> move -> update categories -> git commit."""

    def __init__(
        self,
        config: NootesConfig,
        categories_mgr: CategoriesManager,
        categorizer: Categorizer,
        git_ops: GitOps,
    ) -> None:
        self._config = config
        self._categories = categories_mgr
        self._categorizer = categorizer
        self._git = git_ops

    def process_file(self, file_path: Path) -> CategorizationResult | None:
        """Process a single file: categorize, move, commit.

        Returns the categorization result, or None if the file was skipped.
        """
        if not file_path.exists():
            logger.warning("File no longer exists: %s", file_path)
            return None

        if not is_supported(file_path):
            logger.info("Skipping unsupported file: %s", file_path.name)
            return None

        # Skip files already in a category subdirectory
        relative = file_path.relative_to(self._config.watch_dir)
        if len(relative.parts) > 1:
            logger.debug("Skipping already-organized file: %s", relative)
            return None

        # Skip .nootes internal files and hidden files
        if relative.parts[0].startswith("."):
            return None

        logger.info("Processing: %s", file_path.name)

        # 1. Extract content
        content = extract_content(file_path)

        # 2. Categorize via LLM
        result = self._categorizer.categorize(file_path.name, content)
        logger.info(
            "Categorized '%s' -> %s/%s (confidence: %.2f)",
            file_path.name,
            result.category,
            result.subcategory,
            result.confidence,
        )

        # 3. Update categories master
        self._categories.add_or_update(
            result.category,
            result.category_description,
            result.subcategory,
            result.subcategory_description,
        )

        # 4. Move file to destination
        dest_dir = self._config.watch_dir / result.category / result.subcategory
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / file_path.name

        # Handle name collision
        if dest_path.exists():
            stem = file_path.stem
            suffix = file_path.suffix
            counter = 1
            while dest_path.exists():
                dest_path = dest_dir / f"{stem}_{counter}{suffix}"
                counter += 1

        shutil.move(str(file_path), str(dest_path))
        logger.info("Moved to: %s", dest_path.relative_to(self._config.watch_dir))

        # 5. Git commit
        self._git.commit_organized_file(
            file_path, dest_path, result.category, result.subcategory
        )

        return result

    def sort_all(self) -> int:
        """Sort all files in the root of the watched folder.

        Returns count of processed files.
        """
        count = 0
        for item in sorted(self._config.watch_dir.iterdir()):
            if item.is_file() and not item.name.startswith("."):
                result = self.process_file(item)
                if result is not None:
                    count += 1
        return count
