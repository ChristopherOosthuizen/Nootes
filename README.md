# nootes

AI-powered CLI notes organizer. Drop notes into a folder and nootes automatically categorizes them into a structured hierarchy using OpenAI's gpt-5-nano, then commits everything to a private GitHub repo.

## How It Works

1. You write notes (markdown, docs, PDFs, images) and save them to a watched folder
2. A background daemon detects new files and sends their content to gpt-5-nano
3. The LLM picks (or creates) a category and subcategory
4. The file is moved into the appropriate folder and auto-committed to git

```
~/Notes/
├── Technology/
│   ├── Python/
│   │   └── decorators-cheatsheet.md
│   └── DevOps/
│       └── k8s-notes.pdf
├── Personal/
│   └── Journal/
│       └── 2026-03-10.md
└── .nootes/
    └── categories.json
```

## Installation

```bash
# From source
pip install .

# Or with Homebrew (once published)
brew install nootes
```

## Setup

Create a `.env` file in your working directory:

```bash
OPENAI_API_KEY=sk-your-key-here
NOOTES_WATCH_DIR=~/Notes
GITHUB_REPO=username/my-notes    # optional, creates a private repo
```

Then initialize:

```bash
nootes init
```

This creates the `.nootes/` metadata directory, initializes a git repo, and optionally creates a **private** GitHub repository.

## Commands

| Command | Description |
|---|---|
| `nootes init [--dir PATH]` | Initialize a nootes-managed folder with git and optional private GitHub repo |
| `nootes watch` | Start the background daemon that watches for new files |
| `nootes stop` | Stop the background daemon |
| `nootes sort` | One-time sort of all files currently in the root of the watched folder |
| `nootes full-categorize` | Rebuild all categories from scratch using map-reduce and re-sort every file |
| `nootes status` | Show daemon status, categories, and file counts |

Add `-v` for verbose output: `nootes -v sort`

## Supported File Types

| Type | How it's processed |
|---|---|
| `.md`, `.txt`, `.rst`, `.markdown` | Text content read directly |
| `.docx` | Text extracted via python-docx |
| `.pdf` | Each page rendered as an image and sent to gpt-5-nano vision |
| `.png`, `.jpg`, `.jpeg`, `.gif`, `.bmp`, `.webp`, `.svg` | Sent to gpt-5-nano vision API for understanding |

## Categories Master

nootes maintains a `categories.json` file in `.nootes/` that tracks all categories and their descriptions. The LLM sees existing categories before deciding where to place a new note, so it reuses categories when appropriate and only creates new ones when nothing fits.

Example:

```json
{
  "version": 1,
  "categories": {
    "Technology": {
      "description": "Notes about software, hardware, and tech industry",
      "subcategories": {
        "Python": {
          "description": "Python programming language notes"
        }
      }
    }
  }
}
```

## Full Re-categorization

When your categories get messy or you want a fresh organization:

```bash
nootes full-categorize
```

This runs a 3-pass map-reduce process:

1. **Map** - Summarizes every file using the LLM
2. **Reduce** - Clusters all summaries into an optimal new category tree
3. **Sort** - Re-assigns every file to the new categories

The entire reorganization is committed to git as a single commit.

## Large Document Handling

Documents under 100,000 characters are sent directly to the LLM. Documents exceeding this limit are automatically processed via map-reduce: the text is split into chunks, each chunk is summarized, and the combined summaries are used for categorization.

## Architecture

```
nootes/
├── cli.py               # Click CLI commands
├── config.py             # .env configuration loading
├── daemon.py             # Background daemon (double-fork, PID file, signals)
├── watcher.py            # Watchdog filesystem watcher with debounce
├── readers.py            # Content extraction (text, docx, pdf-as-images, images)
├── categorizer.py        # gpt-5-nano structured output categorization + vision
├── categories.py         # Thread-safe categories master JSON management
├── organizer.py          # Pipeline: extract -> categorize -> move -> commit
├── git_ops.py            # Git operations + private GitHub repo creation
└── full_categorize.py    # 3-pass map-reduce re-categorization
```

## Requirements

- Python 3.9+
- An [OpenAI API key](https://platform.openai.com/api-keys)
- [GitHub CLI](https://cli.github.com/) (`gh`) if you want automatic private repo creation
- Git
