"""阶段 1G 元数据/人工实例描述，不执行视觉分类或实例分割。"""

from uuid import uuid4

from product_studio.analyzers.base import AnalysisOutcome, AnalysisRequest, Analyzer
from product_studio.core.schemas import Evidence, ProductSpec


class GenericProductAnalyzer(Analyzer):
    name = "generic_product"

    def analyze(self, request: AnalysisRequest) -> AnalysisOutcome:
        base_id = request.product_id or f"product_{uuid4().hex}"
        warnings = ["阶段 1G 通用分析只记录元数据/输入实例；自动理解、分割、材质、颜色、文字检测尚未实现。"]
        all_instances = list(request.instances)
        selected = all_instances
        if request.selected_instance:
            selected = [instance for instance in all_instances if instance.instance_id == request.selected_instance]
            if not selected:
                raise ValueError("选中的实例不存在，不能创建假实例。")
        specs = []
        # 无实例时只生成待识别的图片描述结构，绝不假定图片只有一个商品。
        for instance in selected or [None]:
            product_id = f"{base_id}/{instance.instance_id}" if instance else base_id
            spec = ProductSpec(product_id=product_id, source_images=list(request.source_images),
                               detected_instances=list(all_instances), selected_instance=instance.instance_id if instance else None,
                               unknown_properties={name: Evidence() for name in
                                   ("physical_dimensions", "hidden_surfaces", "material_composition", "instance_count",
                                    "visible_colors", "visible_materials", "protected_regions")},
                               analysis_records=[{"analyzer": self.name, "status": "metadata_only",
                                                  "instance_source": "supplied" if instance else "unavailable"}],
                               warnings=warnings.copy())
            spec.validate()
            specs.append(spec)
        return AnalysisOutcome(self.name, "processed", specs=specs, warnings=warnings)
