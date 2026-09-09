"""phewas_core — dataset library, import pipeline and query layer for the PheWAS Browser.

No web-framework dependencies: this package is shared by the FastAPI sidecar, the
`phewas` command line and the test-suite.
"""

__version__ = "0.5.0"

#: Version of the on-disk DuckDB schema written by this package (see schema.py).
SCHEMA_VERSION = 1

#: Version of manifest.json written by this package (see manifest.py).
MANIFEST_VERSION = 1
