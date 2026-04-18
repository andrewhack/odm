"""PyInstaller entry point.

`python -m onvifcfg ...` and the bundled `onvifcfg` binary both land here.
"""

from .cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
