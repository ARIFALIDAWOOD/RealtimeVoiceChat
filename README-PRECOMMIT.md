# Pre-commit Hooks Setup Guide

This project uses [pre-commit](https://pre-commit.com) to automatically check code quality, detect secrets, and enforce formatting standards before each commit.

## Quick Setup

**Windows (using uv):**

```batch
# The script will activate venv and install dependencies automatically
setup-precommit.bat
```

**Manual Setup (using uv):**

```batch
# Activate virtual environment
.venv\Scripts\activate

# Install pre-commit and dev dependencies with uv
uv pip install -r requirements-dev.txt

# Create secrets baseline
python -m detect_secrets scan code/ --baseline .secrets.baseline

# Install pre-commit hooks
pre-commit install
```

## What's Configured

The `.pre-commit-config.yaml` includes:

1. **General Checks:**
   - Trailing whitespace removal
   - End-of-file fixes
   - YAML/JSON validation
   - Large file detection (>10MB)
   - Merge conflict detection
   - Private key detection

2. **Secret Detection (detect-secrets):**
   - Scans all Python files for hardcoded credentials
   - Checks for API keys, passwords, tokens, etc.
   - Uses baseline file (`.secrets.baseline`) to track known false positives

3. **Code Formatting:**
   - **Black**: Automatic code formatting (120 char line length)
   - **isort**: Import sorting

4. **Code Quality:**
   - **flake8**: Python linting (with relaxed rules for this project)
   - **bandit**: Security vulnerability scanning

## Usage

### Automatic (Recommended)

Hooks run automatically before each commit. If any hook fails:
- **Formatting hooks (Black, isort, trailing-whitespace)**: Automatically fix the issues
- **Other hooks**: Fix the issues manually and commit again

### Manual Testing

Run all hooks on all files:
```bash
pre-commit run --all-files
```

Run a specific hook:
```bash
pre-commit run detect-secrets --all-files
pre-commit run black --all-files
```

### Secret Scanning

**Scan for secrets:**
```batch
scan-secrets.bat
```

Or manually:
```bash
python -m detect_secrets scan code/ --baseline .secrets.baseline
```

**Update baseline after reviewing:**
```bash
python -m detect_secrets scan code/ --baseline .secrets.baseline
```

## Handling False Positives

If detect-secrets flags something that's not actually a secret (e.g., example strings, test data):

1. Review the flagged content carefully
2. If it's safe, update the baseline:
   ```bash
   python -m detect_secrets scan code/ --baseline .secrets.baseline
   ```
3. Commit the updated `.secrets.baseline` file

## Skipping Hooks (Emergency Only)

**⚠️ Only skip hooks if absolutely necessary!**

Skip all hooks for one commit:
```bash
git commit --no-verify -m "your message"
```

Skip a specific hook:
```bash
SKIP=detect-secrets git commit -m "your message"
```

## Troubleshooting

**Hooks not running?**
- Ensure pre-commit is installed: `pre-commit --version`
- Reinstall hooks: `pre-commit install`
- Check `.git/hooks/pre-commit` exists

**Secret detection failing?**
- Ensure `.secrets.baseline` exists and is valid JSON
- Recreate baseline: `python -m detect_secrets scan code/ --baseline .secrets.baseline`
- Or run: `scan-secrets.bat` (Windows script using uv)

**Using uv package manager:**
- All scripts (`setup-precommit.bat`, `scan-secrets.bat`) use `uv pip install` for faster, more reliable package management
- Virtual environment must be in `.venv` directory (uv default)
- Scripts automatically activate venv if not already active

**Formatting conflicts?**
- Run `pre-commit run black --all-files` to auto-format
- Run `pre-commit run isort --all-files` to sort imports

## Windows-Specific Notes

- Pre-commit works great on Windows via pip/uv
- All hooks are cross-platform compatible
- For git-secrets alternative, use `scan-secrets.bat` or the detect-secrets hook
