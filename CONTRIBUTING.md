# Contributing

Thanks for your interest in improving this integration!

This repository is the canonical home of the integration maintained by
[@foXaCe](https://github.com/foXaCe). Pull requests target this fork's `main`
branch — there is no upstream contribution flow to follow.

## Reporting issues

- Bugs: use the [bug report form](.github/ISSUE_TEMPLATE/bug_report.yml).
- Ideas: use the [feature request form](.github/ISSUE_TEMPLATE/feature_request.yml).
- Security: see [SECURITY.md](SECURITY.md) — never file a public issue.

## Development setup

```bash
python -m pip install -r requirements-dev.txt
prek install            # installs the git pre-commit hook (drop-in for pre-commit)
```

`prek` is a fast Rust drop-in for `pre-commit` and reads the same
`.pre-commit-config.yaml`. If you prefer the Python runner, `pip install pre-commit`
followed by `pre-commit install` works identically.

## Before opening a pull request

```bash
ruff check custom_components/ tests/
ruff format --check custom_components/ tests/
mypy custom_components/philips_airpurifier_coap/ --ignore-missing-imports
pytest tests/ --cov=custom_components/philips_airpurifier_coap --cov-fail-under=100
```

- Keep test coverage at 100% — the CI gate enforces it.
- Use [Conventional Commits](https://www.conventionalcommits.org/) for messages
  (`feat:`, `fix:`, `ci:`, `docs:`, `refactor:`, `test:`, `chore:`, `build:`).
- Update `CHANGELOG.md` under the `[Unreleased]` section.
- Keep translations in sync (`custom_components/philips_airpurifier_coap/translations/`).

## Pull request flow

1. Create a topic branch: `git checkout -b feat/my-change`
2. Commit with a conventional message.
3. Push and open a PR against `main`.
4. Make sure CI (lint, typing, tests, hassfest, HACS) is green.
