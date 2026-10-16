"""Collect references for image-capable Agent research; does not fabricate VLM output."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from product_studio.references.sources import collect


def main():
    p = argparse.ArgumentParser()
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--url")
    group.add_argument("--local", type=Path, help="Image directory, screenshot, or ZIP")
    p.add_argument("--screenshot", action="store_true")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--saved-html", type=Path, help="Explicit existing page snapshot, no new page request")
    a = p.parse_args()
    result = collect(a.output, url=a.url, local=a.local, screenshot=a.screenshot, saved_html=a.saved_html)
    print(f'{len(result["assets"])} real references; status={result["status"]}; Agent visual analysis still required')


if __name__ == "__main__":
    main()
