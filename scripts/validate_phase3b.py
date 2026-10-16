"""真实任务来源、旧资产保持和推荐候选的交付核验。"""
import json,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.providers.comfyui import save_json,digest
from product_studio.generation.candidates import canonical
from product_studio.generation.candidate_quality import evaluate_candidate


def main():
    path=ROOT/'reports/phase3b_validation.json'
    report=json.loads(path.read_text(encoding='utf-8'))
    backgrounds=json.loads((ROOT/'data/outputs/phase3b/background_manifest.json').read_text(encoding='utf-8'))['records']
    provider_config=json.loads((ROOT/'configs/comfyui_phase3a.json').read_text(encoding='utf-8'))
    jobs=[]
    for entry in backgrounds:
        if entry['status']!='succeeded':
            jobs.append({'instance_id':entry['task']['instance_id'],'candidate_id':entry['task']['candidate_id'],'status':entry['status'],'valid_remote_output':False});continue
        image=Path(entry['background']);record=entry['execution'];history_name='recovery_history.json' if entry['cache']['recovered'] else 'history.json'
        history=json.loads((image.parent/history_name).read_text(encoding='utf-8'));graph=json.loads((image.parent/'submitted_workflow.json').read_text(encoding='utf-8'))
        checks={'history_success':history['status']['completed'] and history['status']['status_str']=='success',
                'prompt_id_matches':history['prompt'][1]==record['prompt_id'],
                'history_graph_matches':canonical(history['prompt'][2])==canonical(graph),
                'submitted_workflow_sha256':digest(canonical(graph))==record['submitted_workflow_sha256'],
                'download_hash':file_sha256(image)==record['background_sha256'],
                'seed_matches':record['seed']==entry['task']['seed'],
                'empty_reference_images':graph[provider_config['mapping']['positive']['node']]['inputs']['images']==[]}
        messages=history['status']['messages'];start=next((v['timestamp'] for k,v in messages if k=='execution_start'),None);end=next((v['timestamp'] for k,v in messages if k=='execution_success'),None)
        jobs.append({'instance_id':entry['task']['instance_id'],'candidate_id':entry['task']['candidate_id'],'prompt_id':record['prompt_id'],
                     'seed':record['seed'],'checks':checks,'valid_remote_output':all(checks.values()),
                     'elapsed_including_queue_seconds':record.get('elapsed_seconds'),
                     'server_execution_seconds':(end-start)/1000 if start is not None and end is not None else None})
    comparisons=[]
    for asset in report['assets']:
        for candidate in asset['candidates']:
            if candidate.get('image'):
                fresh=evaluate_candidate(Path(candidate['image']).parent,asset['preset'])
                directory=Path(candidate['image']).parent
                manifest=json.loads((directory/'composite_manifest.json').read_text(encoding='utf-8'))
                with Image.open(candidate['image']) as im:final=np.asarray(im.convert('RGB'))
                with Image.open(directory/'background.png') as im:bg=np.asarray(im.convert('RGB'))
                with Image.open(directory/'alpha_original.png') as im:alpha=np.asarray(im)
                matrix=np.asarray(manifest['transform']['matrix_source_to_output']);probes=[]
                for x,y in asset.get('background_probes_source_px',[]):
                    dx,dy=np.rint(matrix@np.array([x,y,1])).astype(int)
                    probes.append({'source_point_px':[x,y],'original_alpha':int(alpha[y,x]),
                                   'output_point_px':[int(dx),int(dy)],'new_background_visible':bool(np.array_equal(final[dy,dx],bg[dy,dx]))})
                comparisons.append({'instance_id':asset['instance_id'],'candidate_id':candidate['candidate_id'],
                                    'hard_pass_revalidated':fresh['hard_pass'],'quality_report_matches':fresh==candidate['quality'],
                                    'background_probes':probes,'all_probes_pass':all(p['original_alpha']==0 and p['new_background_visible'] for p in probes),
                                    'mode':asset['mode'],'status':'requires_review'})
    original=json.loads((ROOT/'reports/phase3b_original_hashes.json').read_text(encoding='utf-8'))
    unchanged=all(Path(p).is_file() and file_sha256(p)==sha for p,sha in original.items())
    report['delivery_validation']={'real_jobs':jobs,'candidate_checks':comparisons,'old_files_unchanged':unchanged,
                                   'all_four_real_jobs_valid':len(jobs)==4 and all(j['valid_remote_output'] for j in jobs),
                                   'all_candidates_hard_valid':len(comparisons)==4 and all(c['hard_pass_revalidated'] and c['quality_report_matches'] and c['all_probes_pass'] for c in comparisons),
                                   'visual_quality_human_verified':False}
    save_json(path,report)
    print(json.dumps({'jobs':len(jobs),'all_jobs_valid':report['delivery_validation']['all_four_real_jobs_valid'],'old_files_unchanged':unchanged}))
    return 0 if report['delivery_validation']['all_four_real_jobs_valid'] and report['delivery_validation']['all_candidates_hard_valid'] and unchanged else 1


if __name__=='__main__':raise SystemExit(main())
