"""Thin installed-engine launcher; never searches for a development checkout."""
import sys

def main():
    try:
        from product_studio.runtime import main as engine
    except ImportError:
        print('Engine missing. Install bundled wheel with scripts/install_engine.py and use that venv Python. No checkout fallback.',file=sys.stderr)
        return 3
    return engine(['design',*sys.argv[1:]])

if __name__=='__main__':raise SystemExit(main())
