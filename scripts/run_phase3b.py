"""小规模高级场景候选、评分与商品图集；既有3A产物只读复用。"""
import argparse,json,sys,shutil
from pathlib import Path
from PIL import Image,ImageDraw
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.providers.comfyui import save_json
from product_studio.core.asset_binding import file_sha256
from product_studio.generation.candidates import load_configuration,compose_configuration
from product_studio.generation.compositor import load_foreground,compose_asset
from product_studio.generation.candidate_quality import evaluate_candidate,select_candidates,background_metrics
from generate_phase3b_backgrounds import generate


def previous_image(asset,template):
    base=ROOT/asset['previous_set'];image=base/(template+'.png')
    manifest_path=base/template/'composite_manifest.json';manifest=json.loads(manifest_path.read_text(encoding='utf-8'))
    _,source,gate=load_foreground(ROOT/asset['source_result'],mode=asset['mode'],expected_instance=asset['instance_id'])
    if manifest['output_sha256']!=file_sha256(image) or manifest['source_binding']!=source['binding'] or manifest['mode']!=asset['mode']:raise ValueError('旧图集来源或模式不匹配，不能复用: '+str(image))
    return {'image':str(image),'sha256':file_sha256(image),'source_manifest':str(manifest_path),'kind':'existing_phase3a_'+template,'mode':asset['mode'],'human_review_status':'pending'}


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,default=ROOT/'configs/phase3b_product_set.json')
    parser.add_argument('--ranking-file',type=Path,help='可选具来源说明的人工/辅助排序，不能批准图像')
    a=parser.parse_args();config,presets=load_configuration(a.config,ROOT/'configs/scene_presets.json')
    ordering=json.loads(a.ranking_file.read_text(encoding='utf-8')) if a.ranking_file else {}
    records=generate(config_path=a.config)
    out=ROOT/'data/outputs/phase3b';all_results=[];comparison=[]
    for asset in config['assets']:
        name=asset['instance_id'];preset=presets[asset['preset']];asset_out=out/name;asset_out.mkdir(exist_ok=True)
        previous={t:previous_image(asset,t) for t in ['white_hero','studio','lifestyle']}
        candidates=[]
        for task_record in records:
            task=task_record['task']
            if task['instance_id']!=name:continue
            candidate_id=task['candidate_id'];candidate_dir=asset_out/'candidates'/candidate_id
            if task_record['status']!='succeeded':
                candidates.append({'candidate_id':candidate_id,'quality':{'hard_pass':False,'score':None,'status':'rejected','error':task_record.get('error')},'task':task})
                continue
            rgba,current,gate=load_foreground(ROOT/asset['source_result'],mode=asset['mode'],expected_instance=name)
            config_compose=compose_configuration(asset,preset,rgba,config['output_size_px'])
            manifest_path=candidate_dir/'composite_manifest.json'
            if not manifest_path.exists():
                compose_asset(ROOT/asset['source_result'],task_record['background'],candidate_dir,config_compose,task_record['execution'])
            else:
                existing=json.loads(manifest_path.read_text(encoding='utf-8'))
                if existing['compose_config']!=config_compose or existing['source_binding']!=current['binding'] or existing['background']['background_sha256']!=task_record['execution']['background_sha256']:raise ValueError('已有候选版本不一致，请保留旧版本并更换输出配置')
            quality=evaluate_candidate(candidate_dir,preset)
            save_json(candidate_dir/'quality_report.json',quality)
            candidates.append({'candidate_id':candidate_id,'preset':task['preset'],'image':str(candidate_dir/'final.png'),
                               'manifest':str(manifest_path),'task':task,'quality':quality,
                               'prompt_id':task_record['execution']['prompt_id'],'cache':task_record['cache']})
        fallback={**previous['studio'],'fallback_style':'premium_studio','advanced_scene_success':False}
        selected=select_candidates(candidates,fallback=fallback,preferred_order=ordering.get('rankings',{}).get(name))
        if ordering:selected['ranking_override_provenance']={'path':str(a.ranking_file.resolve()),'sha256':file_sha256(a.ranking_file),'claimed_source':ordering.get('source','unspecified'),'is_asset_approval':False}
        selected['fallback_available']=fallback
        selected['automatic_subjective_quality_verified']=False
        recommended=selected['recommended']
        if recommended:shutil.copyfile(recommended['image'],asset_out/'recommended.png')
        alternatives=[candidate for candidate in selected['ranked'] if not recommended or candidate.get('image')!=recommended.get('image')]
        for index,item in enumerate(alternatives):shutil.copyfile(item['image'],asset_out/f'alternative_{index+1}.png')
        # 图集复用已有主图和影棚，不提交新的白底/影棚任务。
        setdir=asset_out/'product_set';setdir.mkdir(exist_ok=True)
        shutil.copyfile(previous['white_hero']['image'],setdir/'white_hero.png')
        shutil.copyfile(previous['studio']['image'],setdir/'premium_studio.png')
        if recommended:shutil.copyfile(recommended['image'],setdir/'selected_advanced_or_fallback.png')
        with Image.open(Path(previous['lifestyle']['source_manifest']).parent/'background.png') as im:old_background=background_metrics(np.asarray(im.convert('RGB')),preset['placement_region_normalized'])
        report={'instance_id':name,'mode':asset['mode'],'visible_view':asset['visible_view'],'view_evidence':asset['view_evidence'],
                'background_probes_source_px':asset.get('background_probes_source_px',[]),
                'preset':preset,'previous_set':previous,'old_lifestyle_background_metrics':old_background,
                'candidates':candidates,'selection':selected,'asset_human_review_status':'pending',
                'no_automatic_classification':True,'no_new_view':True}
        save_json(asset_out/'manifest.json',report);save_json(asset_out/'product_set/manifest.json',{'source_instance':name,'mode':asset['mode'],'white_hero':previous['white_hero'],'premium_studio':previous['studio'],'selected':selected,'asset_human_review_status':'pending'})
        all_results.append(report)
        panels=[('3A lifestyle',previous['lifestyle']['image'])]
        panels += [(f"3B {c['candidate_id']} score={c['quality'].get('score')}",c.get('image')) for c in candidates]
        panels += [('RECOMMENDED '+selected['recommended_kind'],recommended.get('image') if recommended else None)]
        comparison.append((name+' ['+asset['mode']+']',panels))
    sheet=Image.new('RGB',(1600,len(comparison)*440),'#252525');draw=ImageDraw.Draw(sheet)
    for row,(name,panels) in enumerate(comparison):
        for col,(label,path) in enumerate(panels[:4]):
            draw.text((col*400+8,row*440+7),name+' '+label,fill='white')
            if path:
                with Image.open(path) as im:tile=im.convert('RGB');tile.thumbnail((390,390))
                sheet.paste(tile,(col*400+5,row*440+30))
    sheet.save(ROOT/'reports/phase3b_comparison.png')
    hashes=json.loads((ROOT/'reports/phase3b_original_hashes.json').read_text(encoding='utf-8'))
    unchanged=all(Path(path).is_file() and file_sha256(path)==value for path,value in hashes.items())
    validation={'phase':'3B','status':'requires_user_visual_review','assets':all_results,
                'original_files_checked':len(hashes),'all_original_files_unchanged':unchanged,
                'real_new_task_prompt_ids':list(dict.fromkeys(r['execution']['prompt_id'] for r in records if r['status']=='succeeded')),
                'max_new_task_budget':config['max_new_generation_tasks'],'no_infinite_retry':True,
                'classification_or_visual_language_model_used':False,'human_review_status':'pending',
                'grading_scope':'hard objective checks + explicit heuristics; subjective judgments unverified'}
    save_json(ROOT/'reports/phase3b_validation.json',validation)
    print(json.dumps({'actual_jobs':len(validation['real_new_task_prompt_ids']),'old_files_unchanged':unchanged,'status':validation['status']},ensure_ascii=False))


if __name__=='__main__':main()
