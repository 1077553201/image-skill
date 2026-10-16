"""Category-independent output reproduction and provenance checks, not semantic approval."""
import json
from pathlib import Path

import numpy as np
from PIL import Image

from product_studio.core.asset_binding import file_sha256
from product_studio.generation.compositor import load_foreground,composite_arrays
from product_studio.generation.marketing_renderer import photo_detail
from product_studio.generation.candidates import canonical
from product_studio.providers.comfyui import ComfyUIProvider,digest,save_json


def validate_campaign(root,output,*,remote=False):
    root,output=Path(root).resolve(),Path(output).resolve()
    read=lambda path:json.loads(Path(path).read_text(encoding='utf-8'))
    plan=read(output/'creative_plan.json');manifest=read(output/'manifest.json');request=plan['request']
    rgba,result,gate=load_foreground(plan['source_result'],mode=plan['mode'],expected_instance=plan['instance_id'])
    evidence_checks={key:file_sha256(root/plan[key])==plan[hash_key] for key,hash_key in (
        ('facts_path','facts_sha256'),('analysis_path','analysis_sha256'),('reference_catalog','reference_catalog_sha256'),
        ('agent_analysis_path','agent_analysis_sha256'))}
    if plan.get('agent_input_sha256'):
        evidence_checks['agent_input']=file_sha256(root/request['agent_analysis'])==plan['agent_input_sha256']
    images=[]
    for item in manifest['images']:
        path=Path(item['output_path']);shot=item['brief'];folder=path.parent/'composite'
        with Image.open(path) as im:im.verify()
        with Image.open(path) as im:final=np.asarray(im.convert('RGB'))
        with Image.open(folder/'background.png') as im:bg=np.asarray(im.convert('RGB'))
        with Image.open(folder/'final.png') as im:clean=np.asarray(im.convert('RGB'))
        reproduced,a,_,transform=composite_arrays(rgba,bg,scale=shot['scale'],center_normalized=shot['center'],shadow={'mode':'none'})
        x1,y1,x2,y2=transform['output_visible_extent_xyxy']
        interior=np.zeros(a.shape,bool);interior[max(0,int(y1)):min(a.shape[0],int(y2)+1),max(0,int(x1)):min(a.shape[1],int(x2)+1)]=True
        transparent=(a==0)&interior
        detail_exact=True
        for detail in shot.get('details',[]):
            x,y,w,h=detail['box'];tile,_=photo_detail(rgba,detail['source_bbox'],[w,h])
            expected=Image.new('RGB',(w,h),plan['style']['palette']['navy'])
            expected.paste(tile,((w-tile.width)//2,(h-tile.height)//2),tile.getchannel('A'))
            detail_exact=detail_exact and bool(np.array_equal(np.asarray(expected),final[y:y+h,x:x+w]))
        checks={
            'size':list(final.shape[1::-1])==shot['size_px'],
            'file_hash':file_sha256(path)==item['output_sha256'],
            'plan_hash':item['plan_sha256']==file_sha256(output/'creative_plan.json'),
            'instance_binding':item['source_binding']==result['binding'],
            'original_foreground_hash':file_sha256(folder/'foreground_original.png')==result['binding']['rgba_sha256'],
            'original_alpha_hash':file_sha256(folder/'alpha_original.png')==result['binding']['mask_sha256'],
            'clean_composite_reproduction':bool(np.array_equal(reproduced,clean)),
            'main_product_pixels_preserved':bool(np.array_equal(final[a>0],reproduced[a>0])),
            'transparent_interior_shows_layout_background':bool(np.array_equal(final[transparent],bg[transparent])),
            'real_detail_pixels_reproduced':detail_exact,
            'uniform_scale_only':transform['matrix_source_to_output'][0][0]==transform['matrix_source_to_output'][1][1] and transform['matrix_source_to_output'][0][1]==transform['matrix_source_to_output'][1][0]==0,
            'text_safe':all(t['inside_safe_area'] for t in item['text_checks']),
            'text_contrast':all(t['minimum_glyph_contrast']>=t['required_contrast'] for t in item['text_checks']),
            'no_silent_truncation':all(not t.get('truncated',False) for t in item['text_checks']),
            'review_isolation':item['review_gate']['mode']!='strict' or item['review_gate']['mask_review_valid'],
            'asset_review_pending':item['asset_human_review_status']=='pending'}
        if shot['role']=='lifestyle_scene' and shot.get('scene_level')==2:
            checks['level2_explicit_panel']=bool(shot.get('panels')) and shot.get('presentation')=='editorial_panel'
            checks['level2_real_background']=item['background'].get('provider')=='comfyui' and item['background'].get('status')=='succeeded'
        images.append({'shot_id':shot['shot_id'],'checks':checks,'passed':all(checks.values()),'transparent_interior_pixels':int(transparent.sum()),
                       'text':[t.get('rendered_text',t['text']) for t in item['text_checks']],
                       'fact_ids':shot['fact_ids'],'scene_level':shot['scene_level'],'size_px':shot['size_px'],
                       'image':str(path),'asset_human_review_status':'pending'})
    jobs=[]
    provider=None
    records=read(output/'background_manifest.json')['records']
    for record in records:
        execution=record['execution'];image=Path(record['path']);directory=image.parent
        graph=read(directory/'submitted_workflow.json');pid=execution['prompt_id']
        history=read(directory/'history.json') if (directory/'history.json').exists() else None
        if remote:
            if provider is None:
                config=output/'runtime_config/comfyui.json'
                if not config.is_file():config=root/request.get('comfyui_config','configs/comfyui_phase3a.json')
                provider=ComfyUIProvider(config,project_root=root)
            history=provider.request('/history/'+pid).get(pid)
        graph_match=bool(history and canonical(history['prompt'][2])==canonical(graph))
        checks={'remote_or_saved_history_success':bool(history and history.get('status',{}).get('completed') and history['status'].get('status_str')=='success'),
                'history_graph_exact':graph_match,'submitted_workflow_hash':digest(canonical(graph))==execution['submitted_workflow_sha256'],
                'download_hash':file_sha256(image)==execution['background_sha256'],'generation_did_not_receive_product':execution['product_image_sent_to_AI'] is False}
        jobs.append({'background_id':record['background_id'],'prompt_id':pid,'seed':execution['seed'],
                     'workflow_template_sha256':execution['workflow_template_sha256'],'checks':checks,'passed':all(checks.values()),
                     'history_checked_live':remote,'execution':str(directory/'execution.json'),'image':str(image)})
    passed=all(evidence_checks.values()) and len(images)==request['output_count'] and all(i['passed'] for i in images) and all(j['passed'] for j in jobs)
    report={'product_id':plan['product_id'],'output':str(output),'mode':plan['mode'],'mask_review_valid':gate['mask_review_valid'],
            'engineering_passed':passed,'image_count':len(images),'images':images,'jobs':jobs,'evidence_hashes':evidence_checks,
            'intents':[s['intent'] for s in plan['shots']],'style':plan['style'].get('name','original neutral direction'),
            'scene_gate':plan['scene_gate'],'intent_decisions':plan['intent_decisions'],
            'semantic_and_visual_review':'pending_user_review; automatic checks cannot prove all claims, aesthetics or platform eligibility',
            'agent_image_analysis_not_an_unattended_VLM_service':True}
    save_json(output/'quality_report.json',report)
    return report
