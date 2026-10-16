"""可计算指标与未知风险分开；自动分割或指标正常不等于人工审核。"""

import cv2
import numpy as np

from product_studio.segmentation.mask_processing import validate_alpha,validate_roi


def inspect_mask(rgb,alpha,roi,*,risks=()):
    validate_alpha(alpha,rgb.shape[:2])
    height,width = alpha.shape
    x,y,w,h = validate_roi(roi,width,height)
    local = alpha[y:y+h,x:x+w]
    outside = alpha.copy();outside[y:y+h,x:x+w]=0
    binary = (local>=128).astype(np.uint8)
    count,labels,stats,_ = cv2.connectedComponentsWithStats(binary,8)
    components = [int(stats[i,cv2.CC_STAT_AREA]) for i in range(1,count)]
    contours,hierarchy = cv2.findContours(binary,cv2.RETR_CCOMP,cv2.CHAIN_APPROX_SIMPLE)
    holes = sum(1 for item in hierarchy[0] if item[3]>=0) if hierarchy is not None else 0
    border = np.concatenate((local[0],local[-1],local[:,0],local[:,-1]))
    checks = {"nonempty":bool(np.any(alpha>=128)),"roi_containment":not bool(np.any(outside))}
    warnings = []
    if not checks["nonempty"]: warnings.append("empty_mask")
    if not checks["roi_containment"]: warnings.append("foreground_outside_selected_roi")
    coverage = float(np.mean(binary))
    if coverage < .01: warnings.append("very_low_foreground_coverage")
    if coverage > .98: warnings.append("roi_almost_fully_opaque_possible_background_or_truncation")
    if np.count_nonzero(border>=128): warnings.append("foreground_touches_roi_border_check_target_clipping")
    if sum(area>=16 for area in components)>1: warnings.append("multiple_foreground_components_review_parts_or_multiple_instances")
    if any(area<16 for area in components): warnings.append("tiny_components_possible_noise_or_real_small_parts_not_removed")
    crop=rgb[y:y+h,x:x+w]
    background=crop[local<5]
    interior=cv2.erode(binary,np.ones((3,3),np.uint8)).astype(bool)
    bg_like=0;soft_bg_like=0;bg_median=None
    if len(background)>=16:
        bg_median=np.median(background.astype(np.float32),axis=0)
        similar=np.linalg.norm(crop.astype(np.float32)-bg_median,axis=2)<16
        bg_like=int(np.count_nonzero(similar&interior))
        soft_bg_like=int(np.count_nonzero(similar&(local>0)&(local<255)))
        if bg_like>16:warnings.append("background_like_foreground_color_ambiguous_not_auto_erased")
        if soft_bg_like>16:warnings.append("soft_edge_background_color_possible_halo_check_dark_light_previews")
    warnings.extend([f"declared_risk:{risk}" for risk in risks])
    return {"automatic_status":"failed" if not all(checks.values()) else "needs_human_review",
            "checks":checks,"metrics":{"foreground_pixels_ge128":int(np.count_nonzero(alpha>=128)),
            "roi_foreground_fraction":coverage,"soft_alpha_pixels":int(np.count_nonzero((alpha>0)&(alpha<255))),
            "components_ge128":len(components),"component_areas_px":components,
            "enclosed_background_regions_ge128":holes,"roi_border_foreground_pixels":int(np.count_nonzero(border>=128)),
            "background_median_rgb":None if bg_median is None else bg_median.tolist(),
            "background_like_interior_pixels_ambiguous":bg_like,"soft_alpha_background_like_pixels_halo_proxy":soft_bg_like},
            "semantic_checks":{"target_roi_coverage":"human_review_required","other_instance_inside_roi":"not_verifiable_without_explicit_selection",
                               "background_residue":"color_similarity_proxy_only; white products/highlights are not erased",
                               "fragmentation":"components reported; disconnected parts not automatically removed",
                               "edge_halo":"proxy and dark/light previews; not declared passed",
                               "transparency_and_openings":"human_review_required"},
            "warnings":warnings,
            "not_automatically_verified":["ROI是否只含目标实例","残留背景与遗漏零件","异常断裂是否真实零件间隙",
              "深浅背景边缘光晕","白色/高光区域是否被误删","孔洞与可见内壁","玻璃透明与复杂反射"],
            "human_review_status":"pending"}
