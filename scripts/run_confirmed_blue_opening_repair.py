"""本次明确授权的两个蓝色实例；局部提示为样例数据，不进入通用修复算法。"""
import json,sys
from datetime import datetime,timezone
from pathlib import Path
import cv2
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.segmentation.repair import repair_asset
from product_studio.segmentation.confirmation import record_structure_confirmation


def main():
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    dest=ROOT/'data/intermediate'/('phase2a_fix_confirmed_openings_'+stamp)
    original_files={str(p):file_sha256(p) for p in (ROOT/'data/intermediate').rglob('*') if p.is_file()}
    records=[]
    for instance,cx,old_region in [('blue_left',315,[292,657,46,48]),('blue_right',938,[915,657,46,48])]:
        parent=ROOT/'data/intermediate/phase2a_fix'/instance/'segmentation_result.json'
        old=json.loads(parent.read_text(encoding='utf-8'))
        with Image.open(old['source']['path']) as im:rgb=np.asarray(im.convert('RGB'))
        height,width=rgb.shape[:2];roi=[cx-25,655,50,52]
        # 图像复核白色内部约 y663..693，灰色下缘 y695..701，逐实例提供提示。
        support=np.zeros((height,width),np.uint8);cv2.ellipse(support,(cx,678),(20,18),0,0,360,255,-1)
        bg=np.zeros_like(support);cv2.circle(bg,(cx,677),11,255,-1)
        fg=np.zeros_like(support);x,y,w,h=roi;fg[y:y+h,x:x+w]=255;fg[support>0]=0
        fg[695:y+h,x:x+w]=255 # 明确保护可见灰色金属下缘，不依赖颜色规则。
        evidence={'kind':'explicit_user_physical_structure_confirmation','reviewer':'项目用户（本次对话）',
                  'source':'user message in current conversation','asset_approval':False,
                  'source_text':'蓝色转盘中心金属件下方的小白圆区域，是真实贯穿孔；当前看到的白色是透过孔看到的背景，不是实心零件，不是装饰件。',
                  'pixel_annotation':'AI assistant after local source-image inspection; NOT human-approved boundary'}
        out=dest/instance
        repair_asset(parent,roi,out,editable=support,foreground=fg,background=bg,evidence=[evidence],unknown_initialization='probable_background')
        confirmation={key:old['binding'][key] for key in ('source_id','source_sha256','instance_id')}
        confirmation.update({'reviewer':'项目用户（本次对话）','reviewer_identity_basis':'authenticated project chat actor label; personal name not provided',
                             'fact_type':'physical_structure_confirmation','region':roi,'previous_region':old_region,
                             'confirmation_text':'central lower white circular area is a true through-hole; visible white area is background seen through the opening',
                             'original_user_statement':evidence['source_text'],'parent_mask_version':old['binding']['mask_version'],
                             'new_status':'human_confirmed_opening'})
        _,report=record_structure_confirmation(out/'segmentation_result.json',confirmation,fact_key='central_lower_through_hole')
        with Image.open(out/'before_mask.png') as im:before=np.asarray(im)
        with Image.open(out/'after_mask.png') as im:after=np.asarray(im)
        with Image.open(out/'product_rgba.png') as im:rgba=np.asarray(im)
        ys,xs=np.where(before!=after)
        checks={'outside_roi_unchanged':report['outside_repair_roi_unchanged'],
                'protected_metal_edge_unchanged':bool(np.array_equal(before[fg>0],after[fg>0])),
                'hole_seed_alpha_zero':not bool(np.any(after[bg>0])),
                'center_alpha_before':int(before[677,cx]),'center_alpha_after':int(after[677,cx]),
                'rgb_exact':bool(np.array_equal(rgb,rgba[:,:,:3])),
                'changed_bbox_source_px':[int(xs.min()),int(ys.min()),int(xs.max()-xs.min()+1),int(ys.max()-ys.min()+1)]}
        records.append({'instance_id':instance,'output':str(out),'parent_mask_version':old['binding']['mask_version'],
                        'new_mask_version':report['binding']['mask_version'],'changed_pixels':report['changed_pixels'],
                        'checks':checks,'fact_review_status':'human_confirmed_opening','mask_revision_status':'revised_candidate_generated',
                        'asset_human_review_status':'pending'})
    sheet=Image.new('RGB',(1200,1100),'#222');draw=ImageDraw.Draw(sheet)
    for row,record in enumerate(records):
        out=Path(record['output']);cx=315 if record['instance_id']=='blue_left' else 938
        for col,name in enumerate(['before_dark.png','after_dark.png']):
            with Image.open(out/name) as im:
                frame=im.crop((cx-312,270,cx+312,925));frame.thumbnail((390,410))
                detail=im.crop((cx-26,653,cx+26,706)).resize((300,300),Image.Resampling.NEAREST)
            sheet.paste(frame,(col*400,row*550+30));sheet.paste(detail,(800,row*550+35+col*250));
            draw.text((col*400+10,row*550+10),record['instance_id']+' '+('BEFORE' if col==0 else 'AFTER'),fill='white')
    sheet.save(dest/'confirmed_openings_comparison.png')
    unchanged=all(Path(p).is_file() and file_sha256(p)==digest for p,digest in original_files.items())
    validation={'scope':'only blue_left and blue_right; explicit user-confirmed structure',
                'output_root':str(dest),'records':records,'all_preexisting_intermediate_files_unchanged':unchanged,
                'preexisting_files_checked':len(original_files),'no_other_instance_modified':unchanged,
                'comparison':str(dest/'confirmed_openings_comparison.png'),'final_assets_approved':False}
    (dest/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2),encoding='utf-8')
    (dest/'preexisting_file_hashes.json').write_text(json.dumps(original_files,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(validation,ensure_ascii=False,indent=2))


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    main()
