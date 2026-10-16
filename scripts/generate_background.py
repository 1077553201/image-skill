"""真实远程工作流单张空背景生成。"""
import argparse,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.providers.comfyui import ComfyUIProvider

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--instance',required=True);parser.add_argument('--template',choices=['studio','lifestyle'],required=True)
    parser.add_argument('--seed',type=int,required=True);parser.add_argument('--output-dir',type=Path,required=True)
    a=parser.parse_args();scenes=json.loads((ROOT/'configs/phase3a_scenes.json').read_text(encoding='utf-8'))
    item=next(item for item in scenes['instances'] if item['instance_id']==a.instance)
    template=scenes['templates'][a.template];prompt=template.get('prompt') or template['scenes'][item['scene']]
    provider=ComfyUIProvider(ROOT/'configs/comfyui_phase3a.json',project_root=ROOT)
    path,result=provider.generate(prompt,scenes['negative_prompt'],width=scenes['output_size_px'][0],height=scenes['output_size_px'][1],seed=a.seed,output_dir=ROOT/a.output_dir)
    print(json.dumps({'path':str(path),'prompt_id':result['prompt_id'],'status':result['status']}))
if __name__=='__main__':main()
