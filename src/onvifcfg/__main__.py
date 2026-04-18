"""Entry point for both `python -m onvifcfg` and the PyInstaller bundle.

Absolute import on purpose: PyInstaller runs this file directly as
``__main__`` without any parent package, so a relative ``from .cli``
would fail with ``ImportError: attempted relative import with no known
parent package``.
"""

from onvifcfg.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
