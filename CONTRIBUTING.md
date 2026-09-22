# Contributing to LoveMentor

LoveMentor welcomes first-time contributors. Documentation, tests, demo assets, error messages and small bug fixes are all valuable contributions.

## Quick start

1. Fork the repository and create a branch from `main`.
2. Run the safe preview: `python -m lovementor.demo`.
3. Install development dependencies: `pip install -r requirements.txt`.
4. Run the relevant tests with `python -m pytest tests/ -q`.
5. Keep each pull request focused and explain what a reviewer should verify.

## Good first contributions

- Improve setup, error messages or module documentation.
- Add a synthetic example or test fixture with no personal data.
- Add tests for pure functions and edge cases.
- Improve cross-platform behavior or optional-provider diagnostics.

Never commit chat exports, databases, screenshots, access tokens, contact identifiers, model weights, or other personal data. Run the privacy checks in `tools/private/README.md` before opening a PR that handles data.

## Pull requests

- Use a clear title such as `docs: clarify demo setup`.
- Include tests for behavior changes when practical.
- Update documentation when a user-facing command changes.
- Be kind and assume good intent in review discussions.

The maintainer aims to acknowledge Issues and PRs within seven days. If review is delayed, a polite follow-up is welcome.
