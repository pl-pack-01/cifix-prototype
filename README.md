# Cifix

A CLI tool for fetching, analyzing, and auto-fixing CI failures from GitHub Actions.

## Installation

### Recommended: pipx (isolated install)

```bash
pipx install git+https://github.com/your-username/cifix.git
```

This installs `cifix` as a standalone command in its own virtual environment. Install [pipx](https://pipx.pypa.io/) first if you don't have it.

To upgrade later:

```bash
pipx upgrade cifix
```

To uninstall:

```bash
pipx uninstall cifix
```

### Alternative: pip

```bash
pip install git+https://github.com/your-username/cifix.git
```

### With LLM support

```bash
# Single provider
pipx install "cifix[anthropic] @ git+https://github.com/your-username/cifix.git"

# All providers
pipx install "cifix[llm] @ git+https://github.com/your-username/cifix.git"
```

### For development

```bash
git clone https://github.com/your-username/cifix.git
cd cifix
pip install -e ".[dev]"
```

### Prerequisites

Cifix requires [ruff](https://docs.astral.sh/ruff/) for auto-fix features:

```bash
pip install ruff
```

## Authentication

Cifix requires a GitHub personal access token with `actions:read` scope.

Set it as an environment variable:

```bash
# Linux/macOS
export GITHUB_TOKEN=ghp_your_token_here

# PowerShell
$env:GITHUB_TOKEN = "ghp_your_token_here"
```

Or pass it directly with `--token`.

## Usage

### Fetch workflow run logs

```bash
cifix logs <run_id> --repo <owner/repo>
```

The run ID is the number in the GitHub Actions URL:
`github.com/owner/repo/actions/runs/12345678`

### Classify errors in a CI run

```bash
cifix classify <run_id> --repo <owner/repo>
```

Classifies errors as infrastructure (pipeline/environment) or code issues, with severity levels (fatal, error, warning).

### Apply ruff fixes locally

```bash
cifix fix [repo_path]
```

Runs `ruff format` and `ruff check --fix` on a local repository, displays unified diffs, and verifies the fixes took effect.

### Diagnose and fix a CI failure end-to-end

```bash
cifix diagnose <run_id> --repo <owner/repo>
```

Chains the full pipeline: fetches logs, classifies errors, identifies ruff-fixable issues, applies fixes locally, and verifies results. Also detects `ModuleNotFoundError` / `ImportError` and adds missing packages to your dependency files.

By default, `diagnose` prompts for confirmation before applying fixes. Use `--apply` to skip the prompt, or `--dry-run` to preview without modifying files.

```bash
# Auto-apply without confirmation
cifix diagnose 12345678 --repo owner/repo --apply

# Preview only
cifix diagnose 12345678 --repo owner/repo --dry-run
```

### Examples

```bash
# Fetch raw logs
cifix logs 12345678 --repo octocat/hello-world

# Classify errors
cifix classify 12345678 --repo octocat/hello-world

# Classify with filters
cifix classify 12345678 --repo octocat/hello-world --category code --severity error

# JSON output
cifix classify 12345678 --repo octocat/hello-world --output json

# Fix ruff issues in the current directory
cifix fix

# Preview fixes without modifying files
cifix fix ./my-repo --dry-run

# Fix specific files or directories
cifix fix -t src/ -t tests/

# Full diagnose pipeline
cifix diagnose 12345678 --repo octocat/hello-world

# Diagnose with auto-apply (skip confirmation)
cifix diagnose 12345678 --repo octocat/hello-world --apply

# Diagnose but only classify, skip fixing
cifix diagnose 12345678 --repo octocat/hello-world --no-fix

# Diagnose with JSON output
cifix diagnose 12345678 --repo octocat/hello-world --json-output

# Diagnose with LLM-assisted classification (Anthropic, OpenAI, or Gemini)
cifix diagnose 12345678 --repo octocat/hello-world --llm anthropic
cifix diagnose 12345678 --repo octocat/hello-world --llm openai --explain

# Pass token directly
cifix logs 12345678 --repo myorg/myrepo --token ghp_xxx
```

### Options

```
cifix --help              Show all commands
cifix --version           Show version
cifix logs --help         Show logs options
cifix classify --help     Show classify options
cifix fix --help          Show fix options
cifix diagnose --help     Show diagnose options
```

#### Classify options

| Option | Description |
|--------|-------------|
| `--repo`, `-r` | GitHub repo (owner/repo) — required |
| `--token`, `-t` | GitHub token (or set GITHUB_TOKEN env var) |
| `--provider`, `-p` | CI provider: github, gitlab, jenkins (default: github) |
| `--output`, `-o` | Output format: text, json (default: text) |
| `--category`, `-c` | Filter by category: all, infra, code (default: all) |
| `--severity`, `-s` | Minimum severity: all, fatal, error, warning (default: all) |
| `--no-cache` | Bypass the local log cache |

#### Fix options

| Option | Description |
|--------|-------------|
| `--dry-run` | Show what would change without modifying files |
| `--no-verify` | Skip the post-fix verification step |
| `--no-diff` | Suppress unified diff output |
| `--format-only` | Run ruff format only (skip ruff check --fix) |
| `--check-only` | Run ruff check --fix only (skip ruff format) |
| `--target`, `-t` | Scope fixes to specific files or dirs (repeatable) |
| `--json-output` | Output results as JSON |

#### Diagnose options

| Option | Description |
|--------|-------------|
| `--repo`, `-r` | GitHub repo (owner/repo) — required |
| `--token`, `-t` | GitHub token (or set GITHUB_TOKEN env var) |
| `--provider`, `-p` | CI provider (default: github) |
| `--dry-run` | Preview fixes without modifying files |
| `--apply` | Apply fixes without confirmation prompt |
| `--no-fix` | Classify only, skip auto-fix |
| `--no-verify` | Skip post-fix verification step |
| `--no-diff` | Suppress unified diff output |
| `--repo-path` | Local repo path (default: current directory) |
| `--json-output` | Output everything as JSON |
| `--no-cache` | Bypass the local log cache |
| `--llm` | LLM provider for AI-assisted classification: anthropic, openai, gemini |
| `--explain` | Generate AI explanations for errors (requires --llm) |
| `--api-key` | API key for the LLM provider (or set env var) |

## LLM Integration

Each classified error carries a confidence score (0-100%). Errors below 70% confidence are flagged for LLM review. Unmatched suspicious lines are detected as "unknown" with low confidence.

Pass `--llm` to send ambiguous errors to an AI for reclassification and better suggestions:

```bash
cifix diagnose 12345678 --repo owner/repo --llm anthropic
cifix diagnose 12345678 --repo owner/repo --llm openai --explain
cifix diagnose 12345678 --repo owner/repo --llm gemini --api-key YOUR_KEY
```

Supported providers:

| Provider | Install | Env var |
|----------|---------|---------|
| Anthropic (Claude) | `pip install cifix[anthropic]` | `ANTHROPIC_API_KEY` |
| OpenAI (ChatGPT) | `pip install cifix[openai]` | `OPENAI_API_KEY` |
| Google Gemini | `pip install cifix[gemini]` | `GEMINI_API_KEY` |

Or install all providers at once: `pip install cifix[llm]`

Add `--explain` to generate plain-English explanations for every error. The LLM features are fully optional — cifix works offline with regex-only classification by default.

## Dependency Fixes

When `cifix diagnose` encounters `ModuleNotFoundError` or `ImportError` in CI logs, it automatically:

1. Extracts the missing module name (e.g. `yaml` from `No module named 'yaml'`)
2. Filters out standard library modules (e.g. `os`, `json`, `pathlib`)
3. Maps it to the correct PyPI package (e.g. `yaml` -> `PyYAML`, `cv2` -> `opencv-python`)
4. Adds the package to whichever dependency files exist in your project:
   - `requirements.txt`
   - `pyproject.toml` with `[project.dependencies]` (PEP 621)
   - `pyproject.toml` with `[tool.poetry.dependencies]` (Poetry)

Common import-to-PyPI mappings are built in (PIL -> Pillow, sklearn -> scikit-learn, bs4 -> beautifulsoup4, etc.). Unknown modules fall back to using the module name as the package name.

Use `--dry-run` to preview what would be added without modifying files.

## Caching

Cifix caches downloaded workflow logs locally so repeated runs against the same run ID are near-instant. GitHub Actions logs are immutable once a run completes, so cached data stays valid.

Cache location:
- **Windows**: `%LOCALAPPDATA%\cifix\logs\`
- **Linux/macOS**: `~/.cache/cifix/logs/`

Pass `--no-cache` to any command to bypass the cache and re-fetch from GitHub.

## Project Structure

```
cifix/
├── pyproject.toml
├── README.md
└── src/
    └── cifix/
        ├── __init__.py
        ├── cache.py            # Local disk cache for log downloads
        ├── github.py           # GitHub API client
        ├── classifier.py       # Error classification engine
        ├── patterns.py         # Regex pattern registry
        ├── preprocessor.py     # Log cleaning and step splitting
        ├── formatter.py        # Rich terminal output formatting
        ├── llm_provider.py     # LLM provider abstraction (Anthropic/OpenAI/Gemini)
        ├── llm_advisor.py      # LLM-assisted error review and explanations
        ├── cli/
        │   ├── __init__.py     # Click CLI entry point
        │   ├── fix_cmd.py      # cifix fix command
        │   └── diagnose_cmd.py # cifix diagnose command
        └── fixer/
            ├── ruff_fixer.py   # Ruff auto-fix engine
            └── dep_fixer.py    # Dependency auto-fix engine
```

## License

MIT
