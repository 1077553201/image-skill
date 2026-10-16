"""明确提示的通用局部遮罩修复入口。"""
import argparse,json,sys
from pathlib import Path
import numpy as np
from PIL import Image
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.segmentation.repair import repair_asset
from product_studio.core.asset_binding import file_sha256

def main():
    p=argparse.ArgumentParser(description='局部修复候选；不会自动审核')
    p.add_argument('result',type=Path);p.add_argument('--roi',type=int,nargs=4,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    for key in ('editable','foreground','background','external'):p.add_argument('--'+key,type=Path)
    p.add_argument('--foreground-point',type=int,nargs=2,action='append',default=[])
    p.add_argument('--background-point',type=int,nargs=2,action='append',default=[])
    a=p.parse_args();options={};evidence=[]
    for key in ('editable','foreground','background','external'):
        path=getattr(a,key)
        if path:
            with Image.open(path) as im:
                if im.mode!='L':raise ValueError('提示 mask 必须为完整原图尺寸的 L 灰度图')
                options[key]=np.asarray(im).copy()
            evidence.append({'kind':key,'path':str(path.resolve()),'sha256':file_sha256(path),'status':'estimated_explicit_CLI_prompt; not human_verified'})
    report=repair_asset(a.result,a.roi,a.output_dir,evidence=evidence,foreground_points=a.foreground_point,background_points=a.background_point,**options)
    print(json.dumps({'changed_pixels':report['changed_pixels'],'human_review':'pending'}))
if __name__=='__main__':main()
