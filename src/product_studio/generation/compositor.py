import json
from pathlib import Path
import shutil

import cv2
import numpy as np
from PIL import Image

from product_studio.core.asset_binding import file_sha256,reviewed_mask_is_current
from product_studio.core.schemas import ProductSpec,EvidenceStatus
from product_studio.segmentation.pipeline import load_result


def load_foreground(result_path,*,mode,expected_instance):
    if mode not in {'strict','preview'}:raise ValueError('mode 必须为strict或preview')
    path,result=load_result(result_path);binding=result['binding']
    if result['instance_id']!=expected_instance:raise ValueError('请求实例与遮罩绑定不匹配')
    spec=ProductSpec.from_dict(json.loads((path.parent/'product_spec.json').read_text(encoding='utf-8')))
    if spec.selected_instance!=expected_instance:raise ValueError('规格选中实例不匹配')
    instance=next(i for i in spec.detected_instances if i.instance_id==expected_instance)
    source=next(s for s in spec.source_images if s.source_id==instance.source_id)
    if source.source_id!=binding['source_id'] or source.sha256!=binding['source_sha256'] or list(instance.roi)!=binding['roi']:raise ValueError('来源/ROI绑定不一致')
    if file_sha256(source.path)!=source.sha256:raise ValueError('源图文件已改变')
    if not isinstance(spec.product_mask.value,dict):raise ValueError('缺少绑定的mask资产')
    for key in ('source_id','source_sha256','instance_id','roi','mask_sha256','mask_version','rgba_sha256'):
        if spec.product_mask.value.get(key)!=binding.get(key):raise ValueError('规格mask绑定不匹配: '+key)
    with Image.open(path.parent/'product_rgba.png') as im:
        if im.mode!='RGBA':raise ValueError('前景必须为RGBA')
        rgba=np.asarray(im).copy();profile=im.info.get('icc_profile')
    with Image.open(path.parent/'alpha_mask.png') as im:alpha=np.asarray(im.convert('L'))
    with Image.open(source.path) as im:rgb=np.asarray(im.convert('RGB'));source_profile=im.info.get('icc_profile')
    if rgba.shape[:2]!=(source.height_px,source.width_px) or not np.array_equal(rgba[:,:,:3],rgb) or not np.array_equal(rgba[:,:,3],alpha):raise ValueError('前景已重绘或Alpha/尺寸不符')
    if source_profile!=profile:raise ValueError('前景色彩配置丢失')
    if profile:raise ValueError('当前合成要求显式sRGB素材；带ICC素材需先受控色彩转换，不能静默改变颜色')
    if file_sha256(path.parent/'product_rgba.png')!=binding['rgba_sha256']:raise ValueError('RGBA已改变')
    x,y,w,h=instance.roi;outside=alpha.copy();outside[y:y+h,x:x+w]=0
    if np.any(outside) or not np.any(alpha):raise ValueError('空mask或ROI外混入其他实例')
    reviewed=spec.product_mask.status==EvidenceStatus.HUMAN_VERIFIED and spec.product_mask.value.get('quality')=='reviewed_complete' and reviewed_mask_is_current(spec.product_mask.value,source,instance,spec.product_mask.reviewer)
    if mode=='strict' and not reviewed:raise ValueError('strict需要当前来源/实例/版本有效具名mask审核')
    return rgba,result,{'mode':mode,'mask_review_valid':reviewed,'reviewer':spec.product_mask.reviewer if reviewed else None,
                        'mask_version':binding['mask_version'],'source_id':source.source_id,'instance_id':instance.instance_id,
                        'source_sha256':source.sha256,'asset_visual_review_status':'pending'}


def composite_arrays(rgba,background,*,scale=1.0,center_normalized=(.5,.5),shadow=None):
    if rgba.dtype!=np.uint8 or rgba.ndim!=3 or rgba.shape[2]!=4:raise ValueError('需要uint8 RGBA')
    if background.dtype!=np.uint8 or background.ndim!=3 or background.shape[2]!=3:raise ValueError('需要uint8 RGB背景')
    if not isinstance(scale,(float,int)) or not np.isfinite(scale) or scale<=0:raise ValueError('scale必须为有限正数')
    if len(center_normalized)!=2 or any(not np.isfinite(v) or not 0<=v<=1 for v in center_normalized):raise ValueError('中心必须为[0,1]归一化坐标')
    ys,xs=np.where(rgba[:,:,3]>0)
    if not len(xs):raise ValueError('空前景')
    height,width=background.shape[:2];bbox=[int(xs.min()),int(ys.min()),int(xs.max()+1),int(ys.max()+1)]
    tx=round(center_normalized[0]*width-scale*(bbox[0]+bbox[2]-1)/2)
    ty=round(center_normalized[1]*height-scale*(bbox[1]+bbox[3]-1)/2)
    # 为Lanczos支持域保留边界；不自动裁掉或缩小用户指定商品。
    corners=[scale*bbox[0]+tx,scale*bbox[1]+ty,scale*(bbox[2]-1)+tx,scale*(bbox[3]-1)+ty]
    if corners[0]<4 or corners[1]<4 or corners[2]>width-5 or corners[3]>height-5:raise ValueError('商品会被裁切，请减小比例或调整位置')
    alpha=rgba[:,:,3].astype(np.float32)/255
    premult=np.dstack((rgba[:,:,:3].astype(np.float32)*alpha[:,:,None],alpha))
    matrix=np.array([[scale,0,tx],[0,scale,ty]],np.float32)
    warped=cv2.warpAffine(premult,matrix,(width,height),flags=cv2.INTER_LANCZOS4,borderMode=cv2.BORDER_CONSTANT,borderValue=0)
    a=np.clip(warped[:,:,3],0,1);color=np.clip(warped[:,:,:3],0,255*a[:,:,None])
    bg=background.astype(np.float32);shadow_alpha=np.zeros_like(a)
    if shadow and shadow.get('mode','none')!='none':
        if shadow.get('mode')!='backdrop':raise ValueError('仅支持平面背景柔影，不伪造地面接触阴影')
        opacity=float(shadow.get('opacity',.12));sigma=float(shadow.get('sigma_px',20));dx,dy=shadow.get('offset_px',[8,12])
        if not 0<=opacity<=.5 or not 1<=sigma<=100:raise ValueError('阴影参数超界')
        shadow_alpha=cv2.GaussianBlur(a,(0,0),sigma)*opacity
        shadow_alpha=cv2.warpAffine(shadow_alpha,np.array([[1,0,dx],[0,1,dy]],np.float32),(width,height))
        bg=bg*(1-shadow_alpha[:,:,None])
    final=np.rint(color+bg*(1-a[:,:,None])).clip(0,255).astype(np.uint8)
    transform={'kind':'uniform_scale_and_translation_only','scale':scale,'matrix_source_to_output':matrix.tolist(),
               'source_visible_bbox_xyxy':bbox,'output_visible_extent_xyxy':corners,'center_normalized':list(center_normalized),
               'interpolation':'premultiplied RGB/Alpha; OpenCV Lanczos4','perspective':False,'decontamination':False,
               'shadow':shadow or {'mode':'none'}}
    return final,a,shadow_alpha,transform


def compose_asset(result_path,background_path,output_dir,config,background_record):
    out=Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()):raise ValueError('合成输出目录非空')
    rgba,result,gate=load_foreground(result_path,mode=config['mode'],expected_instance=config['instance_id'])
    background_path=Path(background_path)
    if background_record.get('background_sha256')!=file_sha256(background_path):raise ValueError('背景来源哈希不匹配')
    if background_record.get('status')!='succeeded':raise ValueError('背景任务没有实际成功')
    with Image.open(background_path) as im:im.load();bg=np.asarray(im.convert('RGB')).copy()
    if list(bg.shape[1::-1])!=config['output_size_px']:raise ValueError('背景尺寸不匹配；不隐式拉伸')
    final,a,shadow,transform=composite_arrays(rgba,bg,scale=config.get('scale',1),center_normalized=config.get('center_normalized',[.5,.5]),shadow=config.get('shadow'))
    out.mkdir(parents=True,exist_ok=True)
    Image.fromarray(final).save(out/'final.png');Image.fromarray(np.rint(a*255).astype(np.uint8)).save(out/'transformed_alpha.png')
    if np.any(shadow):Image.fromarray(np.dstack((np.zeros((*a.shape,3),np.uint8),np.rint(shadow*255).astype(np.uint8)))).save(out/'shadow_layer.png')
    shutil.copyfile(Path(result_path).parent/'product_rgba.png',out/'foreground_original.png')
    shutil.copyfile(Path(result_path).parent/'alpha_mask.png',out/'alpha_original.png')
    shutil.copyfile(background_path,out/'background.png')
    # 独立检查背景可见区域和不缩放时的确定像素映射。商品类别没有专有规则。
    if np.any(shadow):bg_visible=np.rint(bg*(1-shadow[:,:,None])).astype(np.uint8)
    else:bg_visible=bg
    transparent=a==0
    exact_opaque=None
    if config.get('scale',1)==1:
        tx=int(transform['matrix_source_to_output'][0][2]);ty=int(transform['matrix_source_to_output'][1][2])
        yy,xx=np.where(rgba[:,:,3]==255)
        exact_opaque=bool(np.array_equal(final[yy+ty,xx+tx],rgba[yy,xx,:3]))
    checks={'size_px':list(bg.shape[1::-1]),'image_integrity':True,'subject_not_cropped':True,
            'transparent_pixels_show_background':bool(np.array_equal(final[transparent],bg_visible[transparent])),
            'opaque_pixels_exact_when_scale_one':exact_opaque,'source_foreground_snapshot_exact':file_sha256(out/'foreground_original.png')==result['binding']['rgba_sha256'],
            'preview_not_promoted_to_strict':gate['mode']!='strict' or gate['mask_review_valid']}
    manifest={'schema_version':'composite.3a.1','status':'succeeded','mode':gate['mode'],'review_gate':gate,
              'source_segmentation_result':str(Path(result_path).resolve()),'source_binding':result['binding'],
              'background':background_record,'compose_config':config,'transform':transform,'checks':checks,
              'output_sha256':file_sha256(out/'final.png'),'visual_review_status':'pending',
              'strict_means':'valid reviewed foreground mask; generated background/composition NOT automatically human approved',
              'warnings':['原始RGB未去污染，细边缘反光/白晕须视觉审核','No new viewpoint; output uses original visible product pixels']}
    (out/'compose_config.json').write_text(json.dumps(config,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'composite_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return manifest
