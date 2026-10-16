"""两个显式商品实例的三模板真实生成/可恢复合成，不改动来源资产。"""
import argparse,json,sys,shutil
from pathlib import Path
from datetime import datetime,timezone

from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.providers.comfyui import ComfyUIProvider,save_json
from product_studio.generation.compositor import compose_asset,load_foreground
from product_studio.core.asset_binding import file_sha256


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser(description='阶段3A实际Qwen背景+原像素合成；需要远程API')
    p.add_argument('--only',help='可选 INSTANCE:TEMPLATE 单张验证')
    p.add_argument('--output-root',type=Path,default=Path('data/outputs/phase3a'))
    args=p.parse_args();out=ROOT/args.output_root;out.mkdir(parents=True,exist_ok=True)
    scenes=json.loads((ROOT/'configs/phase3a_scenes.json').read_text(encoding='utf-8'))
    provider=ComfyUIProvider(ROOT/'configs/comfyui_phase3a.json',project_root=ROOT)
    width,height=scenes['output_size_px'];records=[]
    source_hashes={}
    for instance in scenes['instances']:
        source=ROOT/instance['segmentation_result'];name=instance['instance_id']
        rgba,result,gate=load_foreground(source,mode=instance['mode'],expected_instance=name)
        for f in source.parent.iterdir():
            if f.is_file():source_hashes[str(f)]=file_sha256(f)
        for index,template_name in enumerate(('white_hero','studio','lifestyle')):
            if args.only and args.only!=name+':'+template_name:continue
            base=out/name;base.mkdir(exist_ok=True)
            background_dir=out/'backgrounds'/(name+'_'+template_name)
            template=scenes['templates'][template_name]
            seed=315000+(100 if name=='bag' else 0)+index
            if template_name=='white_hero':
                background_dir.mkdir(parents=True,exist_ok=True)
                background=background_dir/'background.png'
                if not background.exists():Image.new('RGB',(width,height),tuple(template['rgb'])).save(background)
                bg_record={'provider':'python_solid_white','status':'succeeded','rgb':template['rgb'],
                           'background_sha256':file_sha256(background),'actual_size_px':[width,height],
                           'AI_called':False,'visual_review_status':'pending'}
                save_json(background_dir/'execution.json',bg_record)
            else:
                prompt=template.get('prompt') or template['scenes'][instance['scene']]
                background=background_dir/'background.png'
                if (background_dir/'execution.json').exists():
                    bg_record=json.loads((background_dir/'execution.json').read_text(encoding='utf-8'))
                    if (bg_record.get('status')!='succeeded' or bg_record.get('prompt')!=prompt or bg_record.get('negative_prompt')!=scenes['negative_prompt'] or bg_record.get('seed')!=seed or bg_record.get('workflow_template_sha256')!=provider.template_hash or bg_record.get('background_sha256')!=file_sha256(background)):
                        raise ValueError('旧背景任务失败或配置变更，请使用新output-root；不静默重用: '+str(background_dir))
                    print('Reusing recorded real generation '+bg_record['prompt_id'],flush=True)
                else:
                    background,bg_record=provider.generate(prompt,scenes['negative_prompt'],width=width,height=height,seed=seed,output_dir=background_dir)
            compose_config={'instance_id':name,'mode':instance['mode'],'scale':instance['scale'],
                            'center_normalized':instance['center_normalized'],'output_size_px':[width,height],
                            'shadow':{'mode':'none'},'scene_selection':'explicit_config_not_automatic_category_prediction'}
            compose_dir=base/template_name
            if (compose_dir/'composite_manifest.json').exists():
                manifest=json.loads((compose_dir/'composite_manifest.json').read_text(encoding='utf-8'))
                if manifest['compose_config']!=compose_config or manifest['source_binding']!=result['binding'] or manifest['background']['background_sha256']!=bg_record['background_sha256'] or manifest['output_sha256']!=file_sha256(compose_dir/'final.png'):
                    raise ValueError('已存在合成与当前版本不符，请使用新output-root')
            else:manifest=compose_asset(source,background,compose_dir,compose_config,bg_record)
            target=base/(template_name+'.png');shutil.copyfile(compose_dir/'final.png',target)
            record={'instance_id':name,'template':template_name,'output':str(target),
                    'manifest':str(compose_dir/'composite_manifest.json'),'mode':instance['mode'],
                    'mask_review_valid':gate['mask_review_valid'],'background_provider':bg_record['provider'],
                    'prompt_id':bg_record.get('prompt_id'),'seed':bg_record.get('seed'),'checks':manifest['checks'],
                    'visual_review_status':'pending'}
            records.append(record)
            prior_path=base/'manifest.json'
            previous=json.loads(prior_path.read_text(encoding='utf-8')) if prior_path.exists() else {'instance_id':name,'outputs':{}}
            previous['outputs'][template_name]=record;save_json(prior_path,previous)
            print('Composed '+name+':'+template_name+' '+instance['mode'],flush=True)
    report={'phase':'3A','records':records,'real_ComfyUI_prompt_ids':[r['prompt_id'] for r in records if r['prompt_id']],
            'source_files_unchanged':all(file_sha256(path)==sha for path,sha in source_hashes.items()),
            'visual_review_status':'pending','completed_at_utc':datetime.now(timezone.utc).isoformat()}
    save_json(out/('partial_validation.json' if args.only else 'validation.json'),report)
    if not args.only:
        sheet=Image.new('RGB',(1200,850),'#292929');draw=ImageDraw.Draw(sheet)
        for i,record in enumerate(records):
            row,col=divmod(i,3)
            with Image.open(record['output']) as im:tile=im.resize((390,390))
            sheet.paste(tile,(col*400+5,row*425+25))
            draw.text((col*400+10,row*425+5),record['instance_id']+' '+record['template']+' ['+record['mode']+']',fill='white')
        sheet.save(ROOT/'reports/phase3a_comparison.png');save_json(ROOT/'reports/phase3a_validation.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
