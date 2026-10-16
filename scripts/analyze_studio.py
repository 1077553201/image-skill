"""通用商品描述与任务规划入口；旧 analyze_product.py 继续用于圆盘插件。"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from product_studio.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(project_root=PROJECT_ROOT))
