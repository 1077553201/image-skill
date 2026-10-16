"""Report installed engine, dependencies, fonts and explicit services."""
import sys
try:
    from product_studio.runtime import main
except ImportError:
    print('Engine missing: install bundled wheel in a new venv.',file=sys.stderr)
    raise SystemExit(3)
raise SystemExit(main(['preflight',*sys.argv[1:]]))
