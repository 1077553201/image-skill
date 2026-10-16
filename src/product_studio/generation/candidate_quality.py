"""可验证硬约束、启发式背景风险与候选排序；不是AI视觉评分。"""
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image

from product_studio.core.asset_binding import file_sha256
from .compositor import load_foreground,composite_arrays


def background_metrics(background,placement):
    height,width=background.shape[:2]
    gray=cv2.cvtColor(background,cv2.COLOR_RGB2GRAY)
    small=cv2.resize(gray,(256,256),interpolation=cv2.INTER_AREA)
    # 摄影背景的墙地线通常是低对比软边，20/60会漏掉已观察到的3A实例。
    edges=cv2.Canny(small,5,15)
    lines=cv2.HoughLinesP(edges,1,np.pi/180,threshold=45,minLineLength=90,maxLineGap=12)
    horizontal=[]
    if lines is not None:
        for x1,y1,x2,y2 in lines[:,0,:]:
            if abs(y2-y1)<=3 and .45*256<(y1+y2)/2<.96*256:
                length=abs(int(x2)-int(x1))/256
                horizontal.append({'line_normalized':[float(x1/256),float(y1/256),float(x2/256),float(y2/256)],'span_fraction':length})
    line_risk=max((item['span_fraction'] for item in horizontal),default=0.)
    x,y,w,h=placement
    region=edges[round(y*256):round((y+h)*256),round(x*256):round((x+w)*256)]
    edge_density=float(np.mean(region>0))
    return {'horizontal_line_risk':min(1.,line_risk),'horizontal_lines':horizontal,
            'central_edge_density':edge_density,'algorithm':'Canny(5,15)/Hough on 256px grayscale; heuristic only; soft lines may still be missed',
            'cannot_verify':['extra_objects','text_or_logo','duplicate_product','perspective_semantics','paper_fold_semantics','lighting_match']}


def evaluate_candidate(composite_dir,preset):
    directory=Path(composite_dir)
    try:
        manifest=json.loads((directory/'composite_manifest.json').read_text(encoding='utf-8'))
        config=manifest['compose_config']
        rgba,result,gate=load_foreground(manifest['source_segmentation_result'],mode=config['mode'],expected_instance=config['instance_id'])
        with Image.open(directory/'final.png') as im:im.load();final=np.asarray(im.convert('RGB'))
        with Image.open(directory/'background.png') as im:im.load();background=np.asarray(im.convert('RGB'))
        expected,a,shadow,transform=composite_arrays(rgba,background,scale=config.get('scale',1),center_normalized=config.get('center_normalized',[.5,.5]),shadow=config.get('shadow'))
        checks={'output_hash':file_sha256(directory/'final.png')==manifest['output_sha256'],
                'output_dimensions':list(final.shape[1::-1])==config['output_size_px'],
                'source_binding':manifest['source_binding']==result['binding'],
                'foreground_snapshot':file_sha256(directory/'foreground_original.png')==result['binding']['rgba_sha256'],
                'alpha_snapshot':file_sha256(directory/'alpha_original.png')==result['binding']['mask_sha256'],
                'background_hash':file_sha256(directory/'background.png')==manifest['background']['background_sha256'],
                'deterministic_pixel_mapping':np.array_equal(final,expected),
                'uniform_scale_translation_only':transform==manifest['transform'] and not transform['perspective'],
                'no_crop':bool(manifest['checks']['subject_not_cropped']),
                'transparent_regions_show_background':bool(manifest['checks']['transparent_pixels_show_background']),
                'mode_isolated':config['mode']==manifest['mode'] and (config['mode']!='strict' or gate['mask_review_valid'])}
        if config.get('scale',1)==1:checks['opaque_original_pixels_exact']=manifest['checks']['opaque_pixels_exact_when_scale_one'] is True
        if not all(checks.values()):return {'hard_pass':False,'hard_checks':checks,'status':'rejected','score':None,'human_review_status':'pending'}
        metrics=background_metrics(background,preset['placement_region_normalized'])
        opaque=(a>.99).astype(np.uint8)
        boundary=(opaque-cv2.erode(opaque,np.ones((5,5),np.uint8)))>0
        distance=np.linalg.norm(final.astype(np.float32)-background.astype(np.float32),axis=2)/(255*np.sqrt(3))
        contrast=float(distance[boundary].mean()) if np.any(boundary) else 0.
        rules=preset['risk_rules'];edge_risk=min(1.,metrics['central_edge_density']/rules['central_edge_density_threshold'])
        score=round(100*(.6*min(1.,contrast/.30)+.25*(1-edge_risk)+.15*(1-metrics['horizontal_line_risk'])),3)
        flags=[]
        if metrics['horizontal_line_risk']>=rules['horizontal_line_risk_threshold']:flags.append('possible_floor_or_horizontal_edge')
        if metrics['central_edge_density']>=rules['central_edge_density_threshold']:flags.append('central_placement_texture_or_object_risk')
        x,y,w,h=preset['placement_region_normalized'];bw,bh=config['output_size_px']
        extent=transform['output_visible_extent_xyxy']
        placement_fit=extent[0]>=x*bw and extent[1]>=y*bh and extent[2]<=(x+w)*bw and extent[3]<=(y+h)*bh
        if not placement_fit:flags.append('product_outside_preset_placement_area')
        metrics.update(mean_rgb_boundary_contrast=contrast,placement_region_fit=placement_fit)
        return {'hard_pass':True,'hard_checks':checks,'score':score,'score_kind':'documented_heuristic_NOT_AI_visual_score',
                'score_formula':'100*(0.60*min(1,RGBcontrast/0.30)+0.25*(1-central_edge_density/threshold clipped)+0.15*(1-horizontal_line_risk))',
                'background_metrics':metrics,'risk_flags':flags,'status':'requires_review','human_review_status':'pending',
                'subjective_checks':{'objects_text_duplicate_subject':'not_automatically_verified','style_color_lighting_paste_effect':'requires_visual_review'},
                'truth_scope':'original foreground/Alpha mapping preserved; no hidden geometry verification'}
    except (OSError,ValueError,KeyError,TypeError) as exc:
        return {'hard_pass':False,'hard_checks':{},'status':'rejected','score':None,'error':str(exc),'human_review_status':'pending'}


def select_candidates(candidates,*,fallback=None,preferred_order=None):
    eligible=[item for item in candidates if item.get('quality',{}).get('hard_pass') is True]
    ranked=sorted(eligible,key=lambda item:(-item['quality']['score'],item['candidate_id']))
    if preferred_order:
        if len(preferred_order)!=len(set(preferred_order)) or not set(preferred_order).issubset({i['candidate_id'] for i in candidates}):raise ValueError('人工/辅助排序包含重复或未知候选')
        ranked.sort(key=lambda item:preferred_order.index(item['candidate_id']) if item['candidate_id'] in preferred_order else len(preferred_order))
    insufficient=not ranked or all(item['quality'].get('risk_flags') for item in ranked)
    if insufficient:
        return {'recommended':fallback,'recommended_kind':'fallback_premium_studio' if fallback else 'none',
                'advanced_scene_success':False,'status':'requires_review','ranked':ranked,
                'rejected':[i['candidate_id'] for i in candidates if i not in eligible],
                'reason':'no hard-valid advanced candidate or all advanced candidates have heuristic risks',
                'alternatives_retained':True,'human_review_status':'pending'}
    return {'recommended':ranked[0],'recommended_kind':'advanced_candidate','advanced_scene_success':'unverified_pending_visual_review',
            'status':'requires_review','ranked':ranked,'rejected':[i['candidate_id'] for i in candidates if i not in eligible],
            'alternatives_retained':True,'human_review_status':'pending'}
