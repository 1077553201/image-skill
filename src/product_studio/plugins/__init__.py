"""商品插件与显式组合入口；通用核心不导入这里。"""


def default_registry():
    from product_studio.core.registry import AnalyzerRegistry
    from product_studio.analyzers.generic import GenericProductAnalyzer

    def planar_factory():
        from product_studio.plugins.planar_geometry.analyzer import PlanarGeometryAnalyzer
        return PlanarGeometryAnalyzer()

    registry = AnalyzerRegistry()
    registry.register("generic_product", GenericProductAnalyzer)
    registry.register("planar_geometry", planar_factory)
    return registry
