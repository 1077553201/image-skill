from pathlib import Path
import sys

PROJECT_ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT_ROOT/"src"))
from product_studio.segmentation.cli import main

if __name__=="__main__":raise SystemExit(main(project_root=PROJECT_ROOT))
