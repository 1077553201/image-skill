"""Evidence-bound creative-set execution; Agent vision supplies the analyzed design JSON."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.creative.planning import create_plan
from product_studio.generation.candidates import BackgroundCache
from product_studio.providers.comfyui import ComfyUIProvider, save_json


def load_plan(config_path):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    read = lambda key: json.loads((ROOT/config[key]).read_text(encoding='utf-8'))
    plan = create_plan(config, read('facts_path'), read('analysis_path'), read('reference_catalog'), ROOT)
    out = ROOT/plan['output_dir']
    out.mkdir(parents=True, exist_ok=True)
    target = out/'creative_plan.json'
    if target.exists() and json.loads(target.read_text(encoding='utf-8')) != plan:
        raise ValueError('Plan changed; use a new output directory, do not replace prior versions')
    if not target.exists():
        save_json(target, plan)
    return plan, out


def generate_backgrounds(plan, out):
    provider = ComfyUIProvider(ROOT/'configs/comfyui_phase3a.json', project_root=ROOT)
    # A visually revised layout can explicitly reuse its parent's immutable background jobs.
    cache_root = ROOT/plan.get('parent_candidate_set', plan['output_dir'])/'background_tasks'
    cache = BackgroundCache(provider, cache_root)
    tasks = []
    for name, settings in plan['backgrounds'].items():
        tasks.append({'instance_id':plan['instance_id'], 'candidate_id':name, 'mode':plan['mode'],
                      'source_binding':plan['source_binding'], **settings})
    count = sum(not (cache.root/cache.key(t)/'request.json').exists() for t in tasks)
    if count > plan['max_new_generation_tasks']:
        raise ValueError('New generation budget exceeded')
    records = []
    for task in tasks:
        try:
            image, execution, info = cache.get(task)
            record = {'background_id':task['candidate_id'], 'path':str(image.resolve()), 'execution':execution, 'cache':info, 'status':'succeeded'}
        except Exception as exc:
            record = {'background_id':task['candidate_id'], 'status':'failed_or_pending', 'error':str(exc)}
            records.append(record)
            save_json(out/'background_manifest.json', {'records':records, 'automatic_retries':0})
            raise
        records.append(record)
        save_json(out/'background_manifest.json', {'records':records, 'automatic_retries':0})
        print(task['candidate_id']+' background succeeded', flush=True)
    return records


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', type=Path, default=ROOT/'configs/creative_presets/blue_left_4a.json')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--backgrounds-only', action='store_true')
    group.add_argument('--render-only', action='store_true', help='Use already downloaded real backgrounds without network')
    a = parser.parse_args()
    plan, out = load_plan(a.config)
    if a.render_only:
        backgrounds = json.loads((out/'background_manifest.json').read_text(encoding='utf-8'))['records']
    else:
        backgrounds = generate_backgrounds(plan, out)
    if not a.backgrounds_only:
        from product_studio.generation.marketing_renderer import render_set
        render_set(ROOT, plan, out, backgrounds)


if __name__ == '__main__':
    main()
