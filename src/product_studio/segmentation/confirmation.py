"""把明确的人类结构确认附加到新修复候选；不批准整张遮罩或资产。"""
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

from product_studio.core.asset_binding import file_sha256
from product_studio.core.schemas import ProductSpec,Evidence,EvidenceStatus
from .mask_processing import validate_roi
from .pipeline import load_result


def record_structure_confirmation(result_path,confirmation,*,fact_key):
    path,result=load_result(result_path)
    parent_path,parent=load_result(result['parent_result'])
    parent_report_path=parent_path.parent/'repair_report.json'
    previous=json.loads(parent_report_path.read_text(encoding='utf-8'))
    report_path=path.parent/'repair_report.json'
    report=json.loads(report_path.read_text(encoding='utf-8'))
    binding=result['binding']
    for key in ('source_id','source_sha256','instance_id'):
        if confirmation.get(key)!=binding[key] or parent['binding'][key]!=binding[key]:
            raise ValueError('结构确认不能跨来源或实例')
    if confirmation.get('parent_mask_version')!=parent['binding']['mask_version']:
        raise ValueError('结构确认的父版本不匹配')
    if file_sha256(result['source']['path'])!=binding['source_sha256']:raise ValueError('来源图已改变')
    if report['parent_binding']!=parent['binding']:raise ValueError('修复报告父绑定不匹配')
    reviewer=confirmation.get('reviewer')
    if not isinstance(reviewer,str) or not reviewer.strip():raise ValueError('确认必须记录明确审核人')
    if confirmation.get('fact_type')!='physical_structure_confirmation' or confirmation.get('new_status')!='human_confirmed_opening' or not confirmation.get('confirmation_text'):
        raise ValueError('必须提供明确的结构确认事实，不能视为全资产批准')
    previous_region=confirmation.get('previous_region')
    matches=[item for item in previous.get('uncertain_regions',[]) if item.get('bbox_source_px')==previous_region and item.get('status')=='requires_physical_confirmation']
    if len(matches)!=1:raise ValueError('没有唯一匹配的历史待确认区域')
    region=validate_roi(tuple(confirmation['region']),result['source']['width_px'],result['source']['height_px'])
    x,y,w,h=region;sx,sy,sw,sh=binding['roi']
    if not (sx<=x and sy<=y and x+w<=sx+sw and y+h<=sy+sh):raise ValueError('确认区域必须属于当前实例')
    if list(region)!=report['repair_roi']:raise ValueError('事实定位必须与此次修复 ROI 对应')
    if (path.parent/'review_record.json').exists():raise ValueError('结构记录已存在，不覆盖审计历史')
    record={**confirmation,'schema_version':'structure_confirmation.2a_fix.1',
            'reviewer':reviewer.strip(),'reviewed_at':datetime.now(timezone.utc).isoformat(),
            'reviewed_at_semantics':'recorded_at; exact user-message timestamp unavailable',
            'previous_status':'requires_physical_confirmation','new_status':'human_confirmed_opening',
            'affects_mask':True,'human_verified_opening':True,'scope':'structure_fact_only',
            'asset_approved':False,'new_mask_version':binding['mask_version']}
    record_path=path.parent/'review_record.json'
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    for original,name in ((parent_path,'parent_segmentation_result.json'),(parent_report_path,'parent_repair_report.json')):
        shutil.copyfile(original,path.parent/name)
    spec_path=path.parent/'product_spec.json';spec=ProductSpec.from_dict(json.loads(spec_path.read_text(encoding='utf-8')))
    fact=Evidence({'human_verified_opening':True,'region':list(region),'instance_id':binding['instance_id'],
                   'source_id':binding['source_id'],'source_sha256':binding['source_sha256'],
                   'physical_structure':'through_hole','confirmation_record':str(record_path),
                   'confirmation_sha256':file_sha256(record_path),'mask_boundary_human_verified':False},
                  EvidenceStatus.HUMAN_VERIFIED,(binding['source_id'],),'explicit_user_structure_confirmation',
                  reviewer=reviewer.strip(),note='用户确认贯穿孔；像素边界和最终资产尚未批准。')
    spec.verified_facts[fact_key]=fact;spec.unknown_properties.pop(fact_key,None)
    spec.human_review_status='partially_reviewed';spec_path.write_text(spec.to_json(),encoding='utf-8')
    resolved={**matches[0],'status':'human_confirmed_opening','region':list(region),'human_verified_opening':True,
              'confirmation_record':str(record_path),'mask_boundary_human_verified':False}
    report['uncertain_regions']=[item for item in previous.get('uncertain_regions',[]) if item not in matches]
    report['resolved_regions']=[resolved]
    status={'fact_review_status':'human_confirmed_opening','mask_revision_status':'revised_candidate_generated',
            'asset_human_review_status':'pending'}
    boxes=[item['bbox_source_px'] for item in report['changed_regions']]
    changed_bbox=None
    if boxes:
        minx=min(box[0] for box in boxes);miny=min(box[1] for box in boxes)
        changed_bbox=[minx,miny,max(box[0]+box[2] for box in boxes)-minx,max(box[1]+box[3] for box in boxes)-miny]
    audit={'parent_result':str(parent_path),'parent_mask_version':parent['binding']['mask_version'],
           'new_mask_version':binding['mask_version'],'changed_pixels':report['changed_pixels'],
           'changed_region_bbox':changed_bbox,'changed_regions':report['changed_regions'],'method':report['method'],
           'evidence_source':str(record_path),'reviewer':reviewer.strip(),'review_status':status,
           'parent_result_sha256':file_sha256(parent_path),'parent_repair_report_sha256':file_sha256(parent_report_path)}
    report.update(status);report['structure_confirmation']=record;report['revision_audit']=audit
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (path.parent/'updated_repair_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (path.parent/'revision_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf-8')
    result.update(status);result['structure_confirmations']=[record];result['resolved_regions']=[resolved]
    result['uncertain_regions']=report['uncertain_regions'];result['human_review']['status']='pending'
    result['artifacts']={p.name:file_sha256(p) for p in path.parent.iterdir() if p.is_file() and p.name!='segmentation_result.json'}
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return record,report
