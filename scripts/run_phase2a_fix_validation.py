"""真实回归样例提示准备；专项轮廓仅在此验证脚本，未进入修复器。"""
import json,sys
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.segmentation.repair import repair_asset
from product_studio.plugins.planar_geometry.legacy import analyze_image
from product_studio.core.asset_binding import file_sha256

def run():
    base=ROOT/'data/intermediate/phase2a';dest=ROOT/'data/intermediate/phase2a_fix'
    source=ROOT/'data/input/mmexport1791948355130.jpg'
    with Image.open(source) as im:blue=np.asarray(im.convert('RGB'))
    plugin=analyze_image(cv2.cvtColor(blue,cv2.COLOR_RGB2BGR),source_image=str(source),instance='all')
    reports=[];failures=[]
    cases=['blue_left','blue_right','silver_round','black_lower_left','red_left','bag','headphones','watch']
    for case in cases:
        parent=base/case/'segmentation_result.json';old=json.loads(parent.read_text(encoding='utf-8'))
        with Image.open(old['source']['path']) as im:rgb=np.asarray(im.convert('RGB'))
        with Image.open(parent.parent/'alpha_mask.png') as im:alpha=np.asarray(im).copy()
        roi=old['roi'];x,y,w,h=roi
        inside=np.zeros(alpha.shape,np.uint8);inside[y:y+h,x:x+w]=255
        evidence=[];uncertain=[];fail=[]
        if case.startswith('blue_'):
            result=plugin[0 if case=='blue_left' else 1];spec=result.spec
            contourfile=ROOT/'reports'/f'phase2a_fix_{case}_geometry_evidence.json'
            contourfile.write_text(json.dumps(spec,ensure_ascii=False,indent=2),encoding='utf-8')
            holes=np.zeros_like(alpha)
            for hole in spec['cutouts']:
                cv2.fillPoly(holes,[np.asarray(hole['contour_px'],np.int32)],255)
                hm=np.zeros_like(alpha);cv2.fillPoly(hm,[np.asarray(hole['contour_px'],np.int32)],255)
                residual=(hm>0)&(alpha>32)
                coords=np.argwhere(residual)
                fail.append({'cutout_id':hole['cutout_id'],'visible_aperture_bbox':hole['bbox_px'],
                             'residual_pixels_alpha_gt32':int(residual.sum()),
                             'residual_bbox_source_px':None if not len(coords) else [int(coords[:,1].min()),int(coords[:,0].min()),int(coords[:,1].max()-coords[:,1].min()+1),int(coords[:,0].max()-coords[:,0].min()+1)],
                             'basis':'observed visible-background contour, NOT entire machining opening; boundary uncertain'})
            edit=cv2.dilate(holes,np.ones((3,3),np.uint8))&inside
            bg=cv2.erode(holes,np.ones((7,7),np.uint8))
            fg=inside.copy();fg[edit>0]=0
            # 部分边界位于亚像素抗锯齿上，交由局部图像边界判断，不整轮廓填透明。
            evidence=[{'path':str(contourfile),'sha256':file_sha256(contourfile),'source_sha256':old['source']['sha256'],
                       'status':'estimated_annotation','annotator':'AI assistant from observed planar_geometry contours; NOT human verified',
                       'interpretation':'eroded visible background seeds; 3px boundary unknown; dark wall outside support protected'}]
            cx=315 if case=='blue_left' else 938
            uncertain=[{'bbox_source_px':[cx-23,657,46,48],'status':'requires_physical_confirmation',
                        'reason':'central white circular area could be opening or physical part; left unchanged'}]
            failures.append({'case':case,'regions':fail,'ambiguous_regions':uncertain})
        else:
            # 已有透明背景/间隙的保守提示回归，不能声称纠正了未知细节。
            bg=cv2.erode(((alpha==0)&(inside>0)).astype(np.uint8)*255,np.ones((5,5),np.uint8))
            edit=bg.copy();fg=inside.copy();fg[edit>0]=0
            evidence=[{'status':'estimated_annotation','annotator':'AI assistant','basis':'only interior of existing zero-Alpha background editable; all product and soft edges protected',
                       'scope':'non-regression of prompted protected pixels, NOT independent semantic ground truth'}]
        out=dest/case
        if out.exists():raise ValueError('回归目录已存在，不覆盖历史')
        report=repair_asset(parent,roi,out,editable=edit,foreground=fg,background=bg,evidence=evidence,uncertain_regions=uncertain)
        with Image.open(out/'after_mask.png') as im:after=np.asarray(im)
        report['protected_alpha_unchanged']=bool(np.array_equal(alpha[fg>0],after[fg>0]))
        if case.startswith('blue_'):
            core=cv2.erode(holes,np.ones((7,7),np.uint8))>0
            report['visible_background_core_alpha_gt32_before']=int(np.count_nonzero(alpha[core]>32))
            report['visible_background_core_alpha_gt32_after']=int(np.count_nonzero(after[core]>32))
            report['central_uncertain_alpha_unchanged']=bool(np.array_equal(alpha[657:705,cx-23:cx+23],after[657:705,cx-23:cx+23]))
        report['case']=case
        (out/'repair_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        asset=json.loads((out/'segmentation_result.json').read_text(encoding='utf-8'))
        asset['artifacts']['repair_report.json']=file_sha256(out/'repair_report.json')
        (out/'segmentation_result.json').write_text(json.dumps(asset,ensure_ascii=False,indent=2),encoding='utf-8')
        reports.append(report)
    (ROOT/'reports/phase2a_fix_failure_regions.json').write_text(json.dumps(failures,ensure_ascii=False,indent=2),encoding='utf-8')
    # 一行一个实例，原始自动 mask 的深底与修复深底。图中不省略失败样例。
    sheet=Image.new('RGB',(900,len(cases)*300),'#292929');draw=ImageDraw.Draw(sheet)
    for row,case in enumerate(cases):
        out=dest/case;old=json.loads((out/'segmentation_result.json').read_text(encoding='utf-8'));x,y,w,h=old['roi']
        for col,name in enumerate(('before_dark.png','after_dark.png')):
            with Image.open(out/name) as im:tile=im.crop((x,y,x+w,y+h));tile.thumbnail((440,270))
            sheet.paste(tile,(col*450+(440-tile.width)//2,row*300+25))
        draw.text((10,row*300+5),case+' BEFORE | AFTER',fill='white')
    sheet.save(ROOT/'reports/phase2a_fix_comparison.png')
    validation={'phase':'2A-Fix','status':'pending_user_review','second_model_installed':False,'cases':reports,
                'review_sheet':str(ROOT/'reports/phase2a_fix_comparison.png'),'human_approved':False,
                'cross_category_scope':'protected-region conservative regression; no claim unknown edge defects repaired'}
    (ROOT/'reports/phase2a_fix_validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps([{'case':r['case'],'changed_pixels':r['changed_pixels'],'outside_unchanged':r['outside_repair_roi_unchanged']} for r in reports]))

if __name__=='__main__':run()
