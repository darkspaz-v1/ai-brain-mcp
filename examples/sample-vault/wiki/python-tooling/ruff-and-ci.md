---
topic: python-tooling
tags: [python, ruff, ci, github-actions]
---
# Ruff plus GitHub Actions

`ruff check .` runs before the test script in CI. Config lives in `ruff.toml`
(select E, F, W, B; E501 ignored). The workflow runs on Windows for Python 3.12 and 3.13.
