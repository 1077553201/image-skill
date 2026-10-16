"""阶段 1A 兼容入口。圆盘算法已迁入独立 planar_geometry 插件。"""

from product_studio.plugins.planar_geometry.legacy import (
    AnalysisResult,
    ExtractionConfig,
    StructureDetectionError,
    analyze_image,
    circle_metrics,
    contour_data,
    detect_cutouts,
    detect_instances,
    load_image,
    main,
    make_debug_images,
    save_result,
    validate_image,
    validate_roi,
)

__all__ = ['AnalysisResult', 'ExtractionConfig', 'StructureDetectionError', 'analyze_image', 'circle_metrics', 'contour_data', 'detect_cutouts', 'detect_instances', 'load_image', 'main', 'make_debug_images', 'save_result', 'validate_image', 'validate_roi']

if __name__ == "__main__":
    raise SystemExit(main())
