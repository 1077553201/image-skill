"""显式提示驱动的局部遮罩修复；无商品类型或颜色阈值规则。"""
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .mask_processing import validate_alpha,validate_roi,make_previews
from .pipeline import load_result,build_context,export_segmentation,source_alpha_ceiling
from .quality import inspect_mask
from product_studio.core.asset_binding import file_sha256


def local_repair(rgb,before,roi,*,editable=None,foreground=None,background=None,
                 foreground_points=(),background_points=(),iterations=3,external=None,provider=None,
                 unknown_initialization='prior'):
    """提示和遮罩均为全图坐标。前景保护保持原 Alpha，不强制补成255。"""
    validate_alpha(before,rgb.shape[:2]);height,width=before.shape
    x,y,w,h=validate_roi(tuple(roi),width,height)
    if not isinstance(iterations,int) or not 1<=iterations<=10:raise ValueError('iterations 必须为1..10')
    if unknown_initialization not in {'prior','probable_background'}:raise ValueError('未知区域初始值必须为 prior 或 probable_background')
    inside=np.zeros_like(before,bool);inside[y:y+h,x:x+w]=True
    def region(value):
        if value is None:return np.zeros_like(inside)
        validate_alpha(value,before.shape)
        result=value>0
        if np.any(result&~inside):raise ValueError('提示或可编辑区域越过修复 ROI')
        return result
    edit=inside.copy() if editable is None else region(editable)
    fg=region(foreground);bg=region(background)
    def add_points(points,mask):
        for point in points:
            if len(point)!=2 or any(type(v)!=int for v in point):raise ValueError('点坐标必须为整数 x,y')
            px,py=point
            if not (x<=px<x+w and y<=py<y+h):raise ValueError('提示点越过修复 ROI')
            mask[py,px]=True
    add_points(foreground_points,fg);add_points(background_points,bg)
    if np.any(fg&bg):raise ValueError('同一像素不能同时为背景和保护前景')
    if np.any(bg&~edit):raise ValueError('背景提示必须在可编辑区域内')
    editable_unknown=edit&~fg&~bg
    trimap=np.full_like(before,128);trimap[fg]=255;trimap[bg]=0
    after=before.copy();second_provider_metadata=None
    if external is not None:
        validate_alpha(external,before.shape);proposal=external.copy();method='external_mask_local_import'
    elif provider is not None:
        proposal=before.copy();prediction=provider.predict(rgb[y:y+h,x:x+w]);validate_alpha(prediction.alpha,(h,w))
        second_provider_metadata=getattr(prediction,'metadata',{'provider':'unspecified; review required'})
        proposal[y:y+h,x:x+w]=prediction.alpha;method='local_segmentation_provider'
    else:
        if not np.any(bg) or not np.any(fg):raise ValueError('GrabCut 需要明确背景种子和前景保护；未知区域不能自行确认')
        labels=np.where(before[y:y+h,x:x+w]>=128,cv2.GC_PR_FGD,cv2.GC_PR_BGD).astype(np.uint8)
        if unknown_initialization=='probable_background':
            labels[editable_unknown[y:y+h,x:x+w]]=cv2.GC_PR_BGD
        localfg=fg[y:y+h,x:x+w];localbg=bg[y:y+h,x:x+w]
        labels[localfg]=cv2.GC_FGD;labels[localbg]=cv2.GC_BGD
        cv2.setRNGSeed(0)
        cv2.grabCut(np.ascontiguousarray(rgb[y:y+h,x:x+w]),labels,None,
                    np.zeros((1,65),np.float64),np.zeros((1,65),np.float64),iterations,cv2.GC_INIT_WITH_MASK)
        binary=np.isin(labels,[cv2.GC_FGD,cv2.GC_PR_FGD]).astype(np.float32)*255
        # 仅未知边界软化；硬种子和保护区稍后恢复。不是物理 alpha matting。
        soft=cv2.GaussianBlur(binary,(3,3),.5).round().astype(np.uint8)
        proposal=before.copy();proposal[y:y+h,x:x+w]=soft;method='opencv_grabcut_trimap'
    after[editable_unknown]=proposal[editable_unknown];after[bg]=0;after[fg]=before[fg]
    return after,trimap,{'method':method,'foreground_protection':'original Alpha retained',
                        'background_points_source_px':list(background_points),'foreground_points_source_px':list(foreground_points),
                        'editable_pixels':int(edit.sum()),'protected_pixels':int(fg.sum()),'background_seed_pixels':int(bg.sum()),
                        'second_model_used':provider is not None,'second_provider':second_provider_metadata,
                        'iterations':iterations,'unknown_initialization':unknown_initialization,'human_review':'pending'}


def repair_asset(result_path,roi,output_dir,*,evidence=(),uncertain_regions=(),**options):
    path,prior=load_result(result_path)
    rgb,source,spec,orientation=build_context(prior['source']['path'],tuple(prior['roi']),prior['instance_id'],spec_path=path.parent/'product_spec.json')
    if source.sha256!=prior['source']['sha256']:raise ValueError('原图已改变')
    x,y,w,h=validate_roi(tuple(roi),source.width_px,source.height_px)
    sx,sy,sw,sh=prior['roi']
    if not (sx<=x and sy<=y and x+w<=sx+sw and y+h<=sy+sh):raise ValueError('修复 ROI 必须属于所绑定实例')
    with Image.open(path.parent/'alpha_mask.png') as im:before=np.asarray(im.convert('L')).copy()
    with Image.open(path.parent/'raw_alpha_mask.png') as im:raw=np.asarray(im.convert('L')).copy()
    after,trimap,meta=local_repair(rgb,before,roi,**options)
    ceiling=source_alpha_ceiling(source.path)
    if ceiling is not None and np.any(after>ceiling):raise ValueError('修复不可恢复输入透明区域隐藏像素')
    out=Path(output_dir).resolve()
    metadata={'provider':'local_mask_repair',**meta,'initial_provider':prior['provider'],'evidence':list(evidence)}
    result=export_segmentation(rgb,after,raw,source,spec,tuple(prior['roi']),out,metadata,parent=str(path),orientation=orientation)
    before_views=make_previews(rgb,before);after_views=make_previews(rgb,after)
    images={'original_preview.png':rgb,'before_mask.png':before,'after_mask.png':after,'trimap.png':trimap,
            'before_dark.png':before_views['dark_background_preview.png'],'after_dark.png':after_views['dark_background_preview.png'],
            'before_light.png':before_views['light_background_preview.png'],'after_light.png':after_views['light_background_preview.png']}
    changed=before!=after;overlay=rgb.copy();overlay[changed]=np.rint(rgb[changed]*.35+np.array([255,0,180])*.65).astype(np.uint8)
    images['changed_pixels_overlay.png']=overlay
    for key in ('editable','foreground','background','external'):
        if options.get(key) is not None:images[key+'_input.png']=options[key]
    with Image.open(source.path) as original:
        profile=original.info.get('icc_profile') if original.mode in {'RGB','RGBA'} else None
    for name,array in images.items():
        png_options={'icc_profile':profile} if profile and array.ndim==3 else {}
        Image.fromarray(array).save(out/name,**png_options)
    count,labels,stats,_=cv2.connectedComponentsWithStats(changed.astype(np.uint8),8)
    regions=[{'bbox_source_px':s[:4].tolist(),'changed_pixels':int(s[4])} for s in stats[1:]]
    outside=changed.copy();outside[y:y+h,x:x+w]=False
    report={'schema_version':'repair.2a_fix.1','parent_result':str(path),'parent_binding':prior['binding'],'binding':result['binding'],
            'repair_roi':list(roi),'source_coordinate_system':'source_pixels','method':meta,'evidence':list(evidence),
            'uncertain_regions':list(uncertain_regions),'changed_pixels':int(changed.sum()),'changed_regions':regions,
            'outside_repair_roi_unchanged':not bool(outside.any()),'before_quality':inspect_mask(rgb,before,tuple(prior['roi'])),
            'after_quality':result['quality'],'human_review_status':'pending','risk':'seed/contour mistakes may damage edges; review required'}
    (out/'repair_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    result['artifacts']={p.name:file_sha256(p) for p in out.iterdir() if p.is_file() and p.name!='segmentation_result.json'}
    (out/'segmentation_result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
