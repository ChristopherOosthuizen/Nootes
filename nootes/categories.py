"""Categories master file management."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Subcategory:
    name: str
    description: str


@dataclass
class Category:
    name: str
    description: str
    subcategories: dict[str, Subcategory] = field(default_factory=dict)


class CategoriesManager:
    """Thread-safe manager for the categories master file."""

    def __init__(self, categories_file: Path) -> None:
        self._file = categories_file
        self._lock = threading.Lock()
        self._categories: dict[str, Category] = {}
        self._load()

    def _load(self) -> None:
        if not self._file.exists():
            self._categories = {}
            return

        data = json.loads(self._file.read_text(encoding="utf-8"))
        self._categories = {}
        for cat_name, cat_data in data.get("categories", {}).items():
            subcats = {}
            for sub_name, sub_data in cat_data.get("subcategories", {}).items():
                subcats[sub_name] = Subcategory(
                    name=sub_name, description=sub_data["description"]
                )
            self._categories[cat_name] = Category(
                name=cat_name,
                description=cat_data["description"],
                subcategories=subcats,
            )

    def _save(self) -> None:
        data: dict[str, Any] = {"version": 1, "categories": {}}
        for cat in self._categories.values():
            cat_data: dict[str, Any] = {
                "description": cat.description,
                "subcategories": {},
            }
            for sub in cat.subcategories.values():
                cat_data["subcategories"][sub.name] = {
                    "description": sub.description
                }
            data["categories"][cat.name] = cat_data

        self._file.parent.mkdir(parents=True, exist_ok=True)
        self._file.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    def get_all(self) -> dict[str, Category]:
        with self._lock:
            return dict(self._categories)

    def add_or_update(
        self,
        category: str,
        description: str,
        subcategory: str,
        sub_description: str,
    ) -> None:
        with self._lock:
            if category not in self._categories:
                self._categories[category] = Category(
                    name=category, description=description
                )
            cat = self._categories[category]
            if subcategory not in cat.subcategories:
                cat.subcategories[subcategory] = Subcategory(
                    name=subcategory, description=sub_description
                )
            self._save()

    def replace_all(self, categories: dict[str, Category]) -> None:
        with self._lock:
            self._categories = categories
            self._save()

    def summary_for_prompt(self) -> str:
        with self._lock:
            if not self._categories:
                return "No existing categories yet."
            lines = []
            for cat in self._categories.values():
                sub_names = ", ".join(cat.subcategories.keys()) or "none"
                lines.append(
                    f"- {cat.name}: {cat.description} "
                    f"(subcategories: {sub_names})"
                )
            return "\n".join(lines)

    def file_count_by_category(self, watch_dir: Path) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self._lock:
            for cat_name in self._categories:
                cat_dir = watch_dir / cat_name
                if cat_dir.is_dir():
                    counts[cat_name] = sum(
                        1 for f in cat_dir.rglob("*") if f.is_file()
                    )
                else:
                    counts[cat_name] = 0
        return counts
