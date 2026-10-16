"""独立核对真实任务来源与最终像素；不把视觉/语义审核自动通过。"""
import json,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.providers.comfyui import digest,save_json
from product_studio.generation.compositor import load_foreground


def main():
    path=ROOT/'reports/phase3a_validation.json';report=json.loads(path.read_text(encoding='utf-8'))
    provider_config=json.loads((ROOT/'configs/comfyui_phase3a.json').read_text(encoding='utf-8'))
    detailed=[]
    for record in report['records']:
        manifest=json.loads(Path(record['manifest']).read_text(encoding='utf-8'))
        asset=Path(manifest['source_segmentation_result'])
        rgba,source,gate=load_foreground(asset,mode=record['mode'],expected_instance=record['instance_id'])
        with Image.open(record['output']) as im:im.verify()
        with Image.open(record['output']) as im:final=np.asarray(im.convert('RGB'))
        with Image.open(Path(record['manifest']).parent/'background.png') as im:bg=np.asarray(im.convert('RGB'))
        matrix=np.asarray(manifest['transform']['matrix_source_to_output'])
        points=[[170,500],[470,500],[315,785],[315,678]] if record['instance_id']=='blue_left' else [[533,270]]
        probes=[]
        for x,y in points:
            dx,dy=np.rint(matrix@np.array([x,y,1])).astype(int)
            probes.append({'source_point_px':[x,y],'output_point_px':[int(dx),int(dy)],'original_alpha':int(rgba[y,x,3]),
                           'background_visible_exact':bool(np.array_equal(final[dy,dx],bg[dy,dx]))})
        trace=manifest['background'];real=None
        if trace['provider']=='comfyui':
            task=Path(record['manifest']).parents[2]/'backgrounds'/(record['instance_id']+'_'+record['template'])
            history=json.loads((task/'history.json').read_text(encoding='utf-8'))
            workflow=json.loads((task/'submitted_workflow.json').read_text(encoding='utf-8'))
            canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
            real={'prompt_id':trace['prompt_id'],'status_success':history['status']['status_str']=='success' and history['status']['completed'],
                  'history_prompt_id_matches':history['prompt'][1]==trace['prompt_id'],
                  'history_workflow_matches_submitted':digest(canonical(history['prompt'][2]))==digest(canonical(workflow)),
                  'submitted_workflow_hash_valid':digest(canonical(workflow))==trace['submitted_workflow_sha256'],
                  'downloaded_image_hash_valid':file_sha256(task/'background.png')==trace['background_sha256'],
                  'reference_images_not_sent':workflow[provider_config['mapping']['positive']['node']]['inputs']['images']==[],
                  'background_human_review_status':'pending'}
        entry={'instance_id':record['instance_id'],'template':record['template'],'mode':record['mode'],
               'output_sha256_valid':file_sha256(record['output'])==manifest['output_sha256'],
               'output_size_valid':final.shape[:2]==(1024,1024),'gate_revalidated':gate,
               'opening_background_probes':probes,'real_remote_generation_checks':real,
               'automatic_pass':all(p['background_visible_exact'] and p['original_alpha']==0 for p in probes),
               'visual_review_status':'pending'}
        detailed.append(entry)
    report['independent_validation']=detailed
    report['automatic_checks_pass']=all(e['automatic_pass'] and e['output_sha256_valid'] and e['output_size_valid'] and (e['real_remote_generation_checks'] is None or all(value for key,value in e['real_remote_generation_checks'].items() if key not in {'prompt_id','background_human_review_status'})) for e in detailed)
    report['six_outputs_present']=len(detailed)==6
    save_json(path,report)
    print(json.dumps({'outputs':len(detailed),'automatic_checks_pass':report['automatic_checks_pass']}))
    return 0 if report['automatic_checks_pass'] and report['six_outputs_present'] else 1


if __name__=='__main__':raise SystemExit(main())
