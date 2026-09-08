"""PyInstaller entry point (absolute import; __main__.py uses relative imports)."""

import sys

from phewas_server.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
