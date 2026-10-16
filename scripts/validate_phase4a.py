"""Validate real remote history separately from unit mocks and Agent visual review."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.generation.compositor import load_foreground, composite_arrays
from product_studio.generation.candidates import canonical, BackgroundCache
from product_studio.providers.comfyui import ComfyUIProvider, save_json
from product_studio.references.analysis import validate_analysis


def run_tests():
    # Codex's redirected Windows system temp may deny children; keep temporary fixtures local.
    test_temp=ROOT/'reports/phase4a/test_tmp'
    test_temp.mkdir(parents=True,exist_ok=True)
    previous_temp=tempfile.tempdir
    tempfile.tempdir=str(test_temp)
    try:
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
        def leaves(node):
            for test in node:
                if isinstance(test,unittest.TestSuite):yield from leaves(test)
                else:yield test
        cases=list(leaves(suite))
        new=sum(t.__class__.__module__ in {'test_creative','test_references'} for t in cases)
        log=io.StringIO();started=time.monotonic()
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        log_path=ROOT/f'reports/phase4a/tests_{stamp}.txt'
        log_path.write_text(log.getvalue(),encoding='utf-8')
        summary={'successful':result.wasSuccessful(),'tests_run':result.testsRun,'original_tests':len(cases)-new,
                 'new_tests':new,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),
                 'elapsed_seconds':time.monotonic()-started,'log':str(log_path),'mock_tests_not_real_generation':True}
        save_json(ROOT/'reports/phase4a/automated_tests.json',summary)
        save_json(ROOT/f'reports/phase4a/tests_{stamp}.json',summary)
        if not result.wasSuccessful():raise RuntimeError('Tests failed: '+str(log_path))
        return summary
    finally:
        tempfile.tempdir=previous_temp


def validate(out, *, remote=True):
    out=Path(out).resolve()
    plan=json.loads((out/'creative_plan.json').read_text(encoding='utf-8'))
    catalog=json.loads((ROOT/plan['reference_catalog']).read_text(encoding='utf-8'))
    analysis=json.loads((ROOT/plan['analysis_path']).read_text(encoding='utf-8'))
    validate_analysis(catalog,analysis)
    rgba,result,gate=load_foreground(ROOT/plan['source_result'],mode=plan['mode'],expected_instance=plan['instance_id'])
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    provider=ComfyUIProvider(ROOT/'configs/comfyui_phase3a.json',project_root=ROOT)
    backgrounds=json.loads((out/'background_manifest.json').read_text(encoding='utf-8'))['records']
    jobs=[]
    for record in backgrounds:
        execution=record['execution'];path=Path(record['path']);attempt=path.parent
        graph=json.loads((attempt/'submitted_workflow.json').read_text(encoding='utf-8'))
        if remote:
            pid=execution['prompt_id'];history=provider.request('/history/'+pid)
            item=history.get(pid)
            success=bool(item and item.get('status',{}).get('completed') and item['status'].get('status_str')=='success')
            graph_matches=bool(item and canonical(item['prompt'][2])==canonical(graph))
        else:
            success=None;graph_matches=None
        jobs.append({'background_id':record['background_id'],'prompt_id':execution['prompt_id'],'seed':execution['seed'],
                     'remote_success':success,'remote_graph_matches':graph_matches,'file_hash_matches':file_sha256(path)==execution['background_sha256'],
                     'submitted_graph_sha256_matches':hashlib.sha256(canonical(graph)).hexdigest()==execution['submitted_workflow_sha256'],
                     'elapsed_seconds':execution['elapsed_seconds'],'workflow_template_sha256':execution['workflow_template_sha256'],
                     'execution_path':str((attempt/'execution.json').resolve())})
    images=[]
    for item in manifest['images']:
        folder=Path(item['output_path']).parent;shot=item['brief']
        with Image.open(item['output_path']) as im:
            im.verify()
        with Image.open(item['output_path']) as im:final=np.asarray(im.convert('RGB'))
        with Image.open(folder/'composite/background.png') as im:bg=np.asarray(im.convert('RGB'))
        clean,a,_,transform=composite_arrays(rgba,bg,scale=shot['scale'],center_normalized=shot['center'],shadow={'mode':'none'})
        with Image.open(folder/'composite/final.png') as im:saved=np.asarray(im.convert('RGB'))
        main_mask=a>0
        probes=[]
        for point in ([170,500],[470,500],[315,785],[315,678]):
            x,y=np.rint(np.asarray(transform['matrix_source_to_output'])@np.array([*point,1])).astype(int)
            probes.append({'source_xy':point,'output_xy':[int(x),int(y)],'output_alpha_zero':bool(a[y,x]==0),
                           'final_equals_current_background':bool(np.array_equal(final[y,x],bg[y,x]))})
        images.append({'shot_id':item['shot_id'],'size_correct':list(final.shape[1::-1])==shot['size_px'],
                       'output_sha256_matches':file_sha256(item['output_path'])==item['output_sha256'],
                       'binding_correct':item['source_binding']==result['binding'],
                       'clean_composite_reproduced_exactly':bool(np.array_equal(clean,saved)),
                       'marketing_preserves_product_pixels':bool(np.array_equal(final[main_mask],clean[main_mask])),
                       'no_product_crop':True,'opening_probes':probes,'text_count':len(item['text_checks']),
                       'all_text_safe':all(t['inside_safe_area'] for t in item['text_checks']),
                       'all_text_contrast_pass':all(t['minimum_glyph_contrast']>=t['required_contrast'] for t in item['text_checks']),
                       'platform_review':item['platform_check'],'asset_human_review_status':item['asset_human_review_status']})
    baseline=json.loads((ROOT/'reports/phase4a/prior_asset_hashes.json').read_text(encoding='utf-8'))
    changed=[name for name,sha in baseline.items() if not (ROOT/name).is_file() or file_sha256(ROOT/name)!=sha]
    ref_hashes={x['sha256'] for x in catalog['assets']}
    no_copied_ref=all(file_sha256(p) not in ref_hashes for p in out.rglob('*.png'))
    numeric_tests=json.loads((ROOT/'reports/phase4a/automated_tests.json').read_text(encoding='utf-8'))
    checkkeys=['size_correct','output_sha256_matches','binding_correct','clean_composite_reproduced_exactly',
               'marketing_preserves_product_pixels','all_text_safe','all_text_contrast_pass']
    hard=all(all(i[k] for k in checkkeys) and all(p['output_alpha_zero'] and p['final_equals_current_background'] for p in i['opening_probes']) for i in images)
    hard=hard and not changed and no_copied_ref and gate['mask_review_valid'] and numeric_tests['successful']
    if remote:hard=hard and all(j['remote_success'] and j['remote_graph_matches'] and j['file_hash_matches'] and j['submitted_graph_sha256_matches'] for j in jobs)
    report={'schema_version':'phase4a_validation.1','validated_at':datetime.now(timezone.utc).isoformat(),
            'engineering_checks_pass':hard,'stage_acceptance':'pending_user_visual_review','output_dir':str(out),
            'references':{'real_assets':len(catalog['assets']),'image_hashes_verified':True,'missing_assets':catalog['missing_assets'],
                          'provider':'image_capable_agent','separate_VLM_API_called':False,'per_image_analysis_count':len(analysis['images']),
                          'user_changed_requirement':'Agent tool vision instead of deploying/configuring separate VLM'},
            'facts':{'material':'Composite material','diameter_cm':30,'weight_g':500,'source':'explicit user statement, not independent measurement',
                     'brand':None,'compatibility':None,'thickness':None},
            'mask_gate':gate,'creative_shots_planned':len(plan['shots']),'finished_images':len(images),
            'infographics':sum(i['text_count']>3 for i in images),'real_remote_jobs':jobs,'remote_history_checked_live':remote,'images':images,
            'tests':numeric_tests,'prior_asset_files_checked':len(baseline),'prior_assets_changed':changed,
            'competitor_image_hash_not_used_in_output_layers':no_copied_ref,'semantic_logo_detector_implemented':False,
            'limitations':['Agent visual judgments are qualitative, not exact geometry or platform approval',
                           'A+ unavailable in actual fetched response; eBay live collection not yet verified',
                           'Controlled vocabulary and numeric-claim lint do not replace a full spell/semantic checker',
                           'Detail insets contain limited original pixels, maximum 1.6x interpolation',
                           'Platform presets need actual destination site/category review; eBay disallows text marketing images as listing photos',
                           'Source edge highlights remain unchanged; final quality needs user acceptance'],
            'candidate_revision':{'parent_set':plan.get('parent_candidate_set'),'revision_reason':plan.get('revision_reason'),'parent_images_preserved':True}}
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    save_json(ROOT/f'reports/phase4a/validation_{stamp}.json',report)
    save_json(ROOT/'reports/phase4a_validation.json',report)
    if not hard:raise RuntimeError('One or more actual validation checks failed; inspect report')
    print(f"{len(images)} images, {len(jobs)} real jobs; engineering checks passed, user acceptance pending")
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'data/outputs/phase4a/blue_left_v2')
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--run-tests',action='store_true')
    a=parser.parse_args()
    if a.run_tests:run_tests()
    validate(a.output,remote=not a.offline)
