# Third-party components

The application has no third-party runtime dependencies or bundled third-party
code/assets. Python and its standard library are supplied by the user under
their own licenses. Development tooling is installed separately: setuptools
(MIT), build (MIT), and Ruff (MIT). GitHub Actions uses actions/checkout and
actions/setup-python (MIT), referenced by pinned commit IDs; their code is not
redistributed in this repository. No external fixture corpus is copied.
