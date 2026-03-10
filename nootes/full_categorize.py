"""Map-reduce full re-categorization of all notes."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel

from nootes.categories import CategoriesManager, Category, Subcategory
from nootes.categorizer import Categorizer
from nootes.config import NootesConfig
from nootes.git_ops import GitOps
from nootes.readers import extract_content, is_supported

logger = logging.getLogger("nootes.full_categorize")


@dataclass
class FileSummary:
    path: Path
    filename: str
    summary: str


class CategoryTree(BaseModel):
    """Structured output: the complete category tree."""

    class SubcategoryDef(BaseModel):
        name: str
        description: str

    class CategoryDef(BaseModel):
        name: str
        description: str
        subcategories: list["CategoryTree.SubcategoryDef"]

    categories: list[CategoryDef]


CLUSTER_SYSTEM_PROMPT = """\
You are a notes organizer. Given summaries of many notes, design an optimal \
category and subcategory hierarchy to organize them all.

Rules:
- Create 3-15 top-level categories
- Each category should have 1-5 subcategories
- Names should be Title Case, 1-3 words
- Every summary must fit into at least one category
- Categories should be balanced (avoid one catch-all category)
- Descriptions should be 1 sentence each
"""


def full_categorize(config: NootesConfig, on_progress: callable = None) -> int:
    """Run full re-categorization. Returns number of files processed.

    Args:
        config: Application configuration.
        on_progress: Optional callback(message: str) for progress updates.
    """
    client = OpenAI(api_key=config.openai_api_key)
    categories_mgr = CategoriesManager(config.categories_file)
    categorizer = Categorizer(config, categories_mgr)
    git_ops = GitOps(config)

    def progress(msg: str) -> None:
        logger.info(msg)
        if on_progress:
            on_progress(msg)

    # --- PASS 1: MAP - Summarize all files ---
    progress("Pass 1: Summarizing all files...")
    summaries: list[FileSummary] = []

    all_files = _collect_all_files(config.watch_dir)
    for i, file_path in enumerate(all_files, 1):
        progress(f"  [{i}/{len(all_files)}] Summarizing: {file_path.name}")
        content = extract_content(file_path)
        summary = categorizer.summarize_for_clustering(file_path.name, content)
        summaries.append(
            FileSummary(path=file_path, filename=file_path.name, summary=summary)
        )

    if not summaries:
        progress("No files found to categorize.")
        return 0

    # --- PASS 2: REDUCE - Cluster into new categories ---
    progress(f"Pass 2: Clustering {len(summaries)} summaries into categories...")

    summaries_text = "\n".join(f"- {s.filename}: {s.summary}" for s in summaries)

    response = client.beta.chat.completions.parse(
        model=config.openai_model,
        messages=[
            {"role": "system", "content": CLUSTER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Design categories for these {len(summaries)} notes:\n\n"
                    f"{summaries_text}"
                ),
            },
        ],
        response_format=CategoryTree,
        temperature=0.3,
    )

    tree = response.choices[0].message.parsed
    if tree is None:
        raise RuntimeError("LLM returned no category tree.")

    new_categories: dict[str, Category] = {}
    for cat_def in tree.categories:
        subcats = {
            s.name: Subcategory(name=s.name, description=s.description)
            for s in cat_def.subcategories
        }
        new_categories[cat_def.name] = Category(
            name=cat_def.name,
            description=cat_def.description,
            subcategories=subcats,
        )

    categories_mgr.replace_all(new_categories)
    progress(f"Created {len(new_categories)} categories.")

    # --- PASS 3: RE-SORT - Move all files to new locations ---
    progress("Pass 3: Re-sorting all files into new categories...")

    # Move all files back to root
    for s in summaries:
        if s.path.exists():
            dest = config.watch_dir / s.path.name
            if dest != s.path:
                # Handle collision when moving back to root
                if dest.exists():
                    stem = s.path.stem
                    suffix = s.path.suffix
                    counter = 1
                    while dest.exists():
                        dest = config.watch_dir / f"{stem}_{counter}{suffix}"
                        counter += 1
                shutil.move(str(s.path), str(dest))

    # Clean up empty directories
    _cleanup_empty_dirs(config.watch_dir)

    # Re-categorize each file using the new category tree
    from nootes.organizer import Organizer

    organizer = Organizer(config, categories_mgr, categorizer, git_ops)
    count = organizer.sort_all()

    # Git commit the full reorganization
    git_ops.commit_full_reorganize()

    progress(f"Full categorization complete. Processed {count} files.")
    return count


def _collect_all_files(watch_dir: Path) -> list[Path]:
    """Collect all supported files in the watch directory (recursively)."""
    files: list[Path] = []
    for item in watch_dir.rglob("*"):
        if item.is_file() and not any(
            p.startswith(".") for p in item.relative_to(watch_dir).parts
        ):
            if is_supported(item):
                files.append(item)
    return sorted(files)


def _cleanup_empty_dirs(watch_dir: Path) -> None:
    """Remove empty subdirectories (not hidden ones like .nootes or .git)."""
    for item in sorted(watch_dir.rglob("*"), reverse=True):
        if item.is_dir() and not any(
            p.startswith(".") for p in item.relative_to(watch_dir).parts
        ):
            try:
                item.rmdir()
            except OSError:
                pass
