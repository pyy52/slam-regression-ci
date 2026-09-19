# Publishing to PyPI

The package publishes to PyPI from GitHub Actions using
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC), so no
API tokens are stored anywhere. This needs a **one-time manual registration**
by the maintainer.

## One-time setup (maintainer, ~2 minutes)

1. Log in to <https://pypi.org> (and, optionally, <https://test.pypi.org>).
2. Under **Account settings → Publishing**, add a **pending project**:
   - **PyPI project name:** `slam-regression-ci`
   - **Owner:** `pyy52`
   - **Repository:** `slam-regression-ci`
   - **Workflow filename:** `release.yml`
   - **Environment:** `pypi`
3. Save. That is all — future `v*` tags publish automatically.

## How publishing works

- The [`release.yml`](.github/workflows/release.yml) workflow triggers on
  `v*` tags (and supports manual `workflow_dispatch` for retries).
- It builds the sdist and wheel with `python -m build`, then uploads them
  with `pypa/gh-action-pypi-publish` from the `pypi` environment.
- If the project name was never uploaded before, the first run creates it
  (PyPI matches the pending-project registration above).

## Release checklist

1. Update `CHANGELOG.md` (move the Unreleased entries under a new version).
2. Bump `version` in `pyproject.toml` and `src/slam_regression/__init__.py`.
3. Tag and push: `git tag -a vX.Y.Z -m "..." && git push origin vX.Y.Z`.
4. Create the GitHub release with concise notes; PyPI upload happens
   automatically from the same tag.
