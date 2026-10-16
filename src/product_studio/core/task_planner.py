"""阶段 1G 只生成有真实性与来源约束的任务计划，不执行图片生成。"""

from dataclasses import asdict, dataclass
from enum import Enum
from uuid import uuid4

from product_studio.core.schemas import EvidenceStatus as Status, ProductSpec
from product_studio.core.asset_binding import reviewed_mask_is_current


def generation_route(capability,truth_mode,*,mask_review_valid=False):
    """Production capability gate; the older phase-1G plan API below stays compatible."""
    if capability=='image_guided_creative_edit':
        if truth_mode!='concept_creative':raise ValueError('Image editing cannot enter strict_product; use concept_creative')
        return {'capability':capability,'truth_mode':truth_mode,
                'provider':'product_studio.providers.image_guided.ImageGuidedCreativeEditProvider',
                'product_pixels_regenerated':True,'identity_verified':False,'asset_human_review_status':'pending'}
    if capability!='background_only':raise ValueError('Unsupported generation capability')
    if truth_mode not in {'strict_product','source_preserving_preview'}:raise ValueError('Background compositor requires a source-preserving mode')
    if truth_mode=='strict_product' and not mask_review_valid:raise ValueError('strict_product requires a current valid named mask review')
    return {'capability':capability,'truth_mode':truth_mode,
            'provider':'product_studio.providers.comfyui.ComfyUIProvider','product_pixels_regenerated':False,
            'mask_review_valid':mask_review_valid,'asset_human_review_status':'pending'}


class Strategy(str, Enum):
    ORIGINAL_COMPOSITE = "original_composite"
    AI_BACKGROUND = "ai_background"
    VISIBLE_CROP = "visible_crop"
    MULTI_REFERENCE_EDIT = "multi_reference_edit"
    VERIFIED_GEOMETRY_RENDER = "verified_geometry_render"
    SINGLE_IMAGE_CONCEPT = "single_image_concept"


@dataclass(frozen=True)
class OutputRequest:
    strategy: Strategy
    target_view: str | None = None
    allow_concept: bool = False


@dataclass(frozen=True)
class TaskPlan:
    task_id: str
    product_id: str
    selected_instance: str | None
    strategy: str
    target_view: str | None
    authenticity_level: str  # source_preserving_intent / requires_verification / verified_geometry_basis / concept_only
    status: str  # planned / blocked; never executed
    provenance: dict
    prerequisites: tuple[str, ...]
    execution_status: str = "not_implemented_in_phase1g"
    output_verified: bool = False

    def to_dict(self):
        return asdict(self)


def plan_task(spec: ProductSpec, request: OutputRequest) -> TaskPlan:
    spec.validate()
    if not isinstance(request.strategy, Strategy):
        raise ValueError("必须选择明确的 Strategy。")
    prerequisites = []
    strategy = request.strategy
    level = "source_preserving_intent"
    sources = {source.source_id: source for source in spec.source_images}
    instance = next((item for item in spec.detected_instances if item.instance_id == spec.selected_instance), None)
    if instance is None:
        prerequisites.append("需要明确选中的真实商品实例；不假定整张照片只有一个商品。")
    applicable_sources = [instance.source_id] if instance else []
    visible_view = spec.visible_view
    view_known = visible_view.status in {Status.OBSERVED, Status.HUMAN_VERIFIED} and (
        instance is not None and instance.source_id in visible_view.sources)
    novel_view = bool(request.target_view) and (not view_known or request.target_view != visible_view.value)

    if strategy in {Strategy.ORIGINAL_COMPOSITE, Strategy.AI_BACKGROUND}:
        mask = spec.product_mask
        if mask.status != Status.HUMAN_VERIFIED or not isinstance(mask.value, dict) or mask.value.get("quality") != "reviewed_complete" or not mask.value.get("artifact") or instance is None or mask.value.get("instance_id") != instance.instance_id or instance.source_id not in mask.sources:
            prerequisites.append("需要绑定当前实例、人工审核且完整的 mask；阶段 1A 部分遮罩不满足。")
        elif not reviewed_mask_is_current(mask.value,sources[instance.source_id],instance,mask.reviewer):
            prerequisites.append("遮罩审核的来源/实例/文件版本不匹配或资产已修改，需要重新审核。")
        if novel_view:
            prerequisites.append("保真合成/背景策略不能改变为未验证视角。")
        if strategy == Strategy.AI_BACKGROUND:
            prerequisites.append("需要真实 API Workflow 和已验证生成 Provider；当前未接入。")
    elif strategy == Strategy.VISIBLE_CROP:
        if novel_view:
            prerequisites.append("局部特写只能裁剪当前可见像素，不能提供隐藏角度。")
    elif strategy == Strategy.MULTI_REFERENCE_EDIT:
        level = "requires_verification"
        same_product = spec.verified_facts.get("same_product_source_ids")
        selected_sources = same_product.value if same_product and same_product.status == Status.HUMAN_VERIFIED else None
        if not isinstance(selected_sources, list) or len(set(selected_sources)) < 2 or not set(selected_sources).issubset(sources) or not set(selected_sources).issubset(same_product.sources if same_product else ()):
            prerequisites.append("至少两张参考图必须人工确认属于同一商品，不能因放在一起自动合并。")
        else:
            applicable_sources = selected_sources
        if novel_view:
            prerequisites.append("目标视角的结构覆盖需额外人工验证，参考图数量本身不能证明它。")
        prerequisites.append("需要真实编辑 Provider；生成后还需保真质检，当前未接入。")
    elif strategy == Strategy.VERIFIED_GEOMETRY_RENDER:
        level = "requires_verification"
        model = spec.verified_facts.get("geometry_model")
        views = spec.verified_facts.get("verified_views")
        model_valid = model and model.status == Status.HUMAN_VERIFIED and isinstance(model.value, dict) and model.value.get("asset") and instance is not None and model.value.get("instance_id") == instance.instance_id and instance.source_id in model.sources
        view_valid = views and views.status == Status.HUMAN_VERIFIED and isinstance(views.value, list) and request.target_view in views.value and instance is not None and instance.source_id in views.sources
        if not model_valid or not view_valid or not request.target_view:
            prerequisites.append("需要人工验证的几何资产，以及明确覆盖目标角度的 verified_views。")
        else:
            level = "verified_geometry_basis"
        if model and instance and instance.source_id not in model.sources:
            prerequisites.append("几何验证来源未绑定当前选中的实例来源。")
        prerequisites.append("需要实际建模/渲染后端与验证记录；当前未实现。")
    elif strategy == Strategy.SINGLE_IMAGE_CONCEPT:
        level = "concept_only"
        if not request.allow_concept:
            prerequisites.append("概念生成需要明确 allow_concept，不作为真实商品图。")
        prerequisites.append("需要真实生成 Provider；当前未接入，所有隐藏结构只能是概念推测。")

    return TaskPlan(
        task_id=f"task_{uuid4().hex}", product_id=spec.product_id, selected_instance=spec.selected_instance,
        strategy=strategy.value, target_view=request.target_view, authenticity_level=level,
        status="blocked" if prerequisites else "planned",
        provenance={"source_images": [asdict(sources[key]) for key in applicable_sources],
                    "selected_instance": asdict(instance) if instance else None,
                    "input_schema": spec.schema_version,
                    "source_binding": "same_product_human_verified" if strategy == Strategy.MULTI_REFERENCE_EDIT and len(applicable_sources) > 1 else "selected_instance_only",
                    "human_review_status": spec.human_review_status},
        prerequisites=tuple(prerequisites),
    )
