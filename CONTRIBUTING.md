# Contributing to slam-regression-ci

Thanks for your interest in improving this project — issues, bug reports, and
pull requests are all welcome.

## Development setup

```bash
git clone https://github.com/pyy52/slam-regression-ci.git
cd slam-regression-ci
python3 -m pip install -e ".[dev]"
python3 -m pytest
```

Python 3.8+ is supported and tested (3.8–3.12 in CI).

## How to submit changes

1. Open an issue first for anything that changes scope or public behavior.
2. Create a feature branch from `main`.
3. Add or update tests for your change; keep the existing tests passing.
4. Run `python3 -m ruff check .` before pushing.
5. Open a pull request with a short description and, if applicable,
   `Closes #<issue>`.

## Commit messages

Use plain, descriptive commit messages in the conventional style:

```text
feat: add trajectory regression comparison
fix: handle empty trajectory inputs
docs: add GitHub Actions example
test: cover threshold failure behavior
chore: prepare v0.1.0 release
```

## Code style

- Keep dependencies minimal: runtime deps are numpy and PyYAML.
- Prefer small, pure functions in `src/slam_regression/` that are easy to test.
- Public behavior changes need a `CHANGELOG.md` entry.

## Maintenance disclosure

This project is maintained with the help of AI coding assistants for routine
engineering work (tests, docs, CI upkeep). All changes are reviewed before
merge, and releases are made deliberately. External contributors are never
required to disclose or use any particular tooling.
