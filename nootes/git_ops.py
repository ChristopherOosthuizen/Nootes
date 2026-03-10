"""Git operations for auto-committing organized notes."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import git as gitpython

from nootes.config import NootesConfig

logger = logging.getLogger("nootes.git_ops")


class GitOps:
    """Manages git operations within the watched directory."""

    def __init__(self, config: NootesConfig) -> None:
        self._config = config
        self._repo: gitpython.Repo | None = None

    def _get_repo(self) -> gitpython.Repo:
        if self._repo is None:
            try:
                self._repo = gitpython.Repo(str(self._config.watch_dir))
            except gitpython.InvalidGitRepositoryError:
                logger.warning(
                    "No git repo found at %s. Git operations disabled.",
                    self._config.watch_dir,
                )
                raise
        return self._repo

    def init_repo(self) -> gitpython.Repo:
        """Initialize a new git repo in the watched directory."""
        repo = gitpython.Repo.init(str(self._config.watch_dir))
        self._repo = repo
        logger.info("Initialized git repo at %s", self._config.watch_dir)
        return repo

    def create_private_remote(self, repo_name: str) -> None:
        """Create a private GitHub repo using gh CLI and set it as remote.

        Args:
            repo_name: Name for the GitHub repo (e.g. 'my-notes' or 'user/my-notes')
        """
        try:
            # Create private repo on GitHub
            subprocess.run(
                [
                    "gh",
                    "repo",
                    "create",
                    repo_name,
                    "--private",
                    "--source",
                    str(self._config.watch_dir),
                    "--push",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Created private GitHub repo: %s", repo_name)
        except FileNotFoundError:
            logger.warning(
                "gh CLI not found. Install GitHub CLI to enable remote repo creation."
            )
        except subprocess.CalledProcessError as e:
            logger.warning("Failed to create GitHub repo: %s", e.stderr.strip())

    def commit_organized_file(
        self,
        original_path: Path,
        new_path: Path,
        category: str,
        subcategory: str,
    ) -> None:
        """Stage and commit an organized file move."""
        try:
            repo = self._get_repo()
        except gitpython.InvalidGitRepositoryError:
            return

        relative_new = new_path.relative_to(self._config.watch_dir)
        relative_old = original_path.relative_to(self._config.watch_dir)

        repo.index.add([str(relative_new)])

        try:
            repo.index.remove([str(relative_old)])
        except Exception:
            pass  # File may not have been tracked yet

        # Also stage the updated categories file
        categories_rel = self._config.categories_file.relative_to(
            self._config.watch_dir
        )
        if self._config.categories_file.exists():
            repo.index.add([str(categories_rel)])

        message = f"Categorized: {original_path.name} -> {category}/{subcategory}"
        repo.index.commit(message)
        logger.info("Git commit: %s", message)

        self._push_if_remote(repo)

    def commit_full_reorganize(self) -> None:
        """Stage and commit after a full reorganization."""
        try:
            repo = self._get_repo()
        except gitpython.InvalidGitRepositoryError:
            return

        repo.git.add("--all")
        repo.index.commit(
            "Full reorganization: rebuilt categories and re-sorted all notes"
        )
        logger.info("Git commit: full reorganization")

        self._push_if_remote(repo)

    def _push_if_remote(self, repo: gitpython.Repo) -> None:
        """Push to remote if one is configured."""
        try:
            if repo.remotes:
                repo.remotes.origin.push()
                logger.info("Pushed to remote.")
        except Exception as e:
            logger.warning("Failed to push to remote: %s", e)
