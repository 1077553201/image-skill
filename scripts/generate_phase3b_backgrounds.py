"""四个以内真实任务；持久缓存保证恢复时不重复提交。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.providers.comfyui import ComfyUIProvider,save_json
from product_studio.generation.compositor import load_foreground
from product_studio.generation.candidates import load_configuration,make_plan,BackgroundCache


def generate(root=ROOT,config_path=None,provider=None):
    config,presets=load_configuration(config_path or root/'configs/phase3b_product_set.json',root/'configs/scene_presets.json')
    provider=provider or ComfyUIProvider(root/'configs/comfyui_phase3a.json',project_root=root)
    bindings={a['instance_id']:load_foreground(root/a['source_result'],mode=a['mode'],expected_instance=a['instance_id'])[1]['binding'] for a in config['assets']}
    plan=make_plan(config,presets,provider,bindings);cache=BackgroundCache(provider,root/'data/outputs/phase3b/background_tasks')
    new_tasks=sum(not (cache.root/cache.key(task)/'request.json').exists() for task in plan)
    if new_tasks>config['max_new_generation_tasks']:raise ValueError('新增真实任务超过本轮预算，未提交')
    output=root/'data/outputs/phase3b';output.mkdir(parents=True,exist_ok=True)
    save_json(output/'plan.json',{'tasks':plan,'new_tasks_before_run':new_tasks,'automatic_retries':0,'classification_model_used':False})
    records=[]
    for task in plan:
        try:
            image,record,cache_info=cache.get(task)
            records.append({'task':task,'status':'succeeded','background':str(image),'execution':record,'cache':cache_info})
        except Exception as exc:
            records.append({'task':task,'status':'failed_or_pending','error':{'type':type(exc).__name__,'message':str(exc)},'cache_key':cache.key(task)})
        save_json(output/'background_manifest.json',{'records':records,'no_auto_retry':True})
        print(task['instance_id']+' '+task['candidate_id']+' '+records[-1]['status'],flush=True)
    return records


if __name__=='__main__':
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    generate()
