# Contributing

Use Python 3.11 or newer and a virtual environment. Install with
`python -m pip install -e . -r requirements-dev.txt`.

Before proposing a change, run:

```sh
python -m unittest discover -s tests -v
python -m ruff check .
python -m ruff format --check .
python -m build
```

Report a minimal reproduction using synthetic data. Add a behavioral regression
test for a fix. Discuss larger changes in an issue first. Submit only code you
are entitled to contribute and retain third-party copyright/license notices.
Maintainers review contributions manually; CI never commits code.
