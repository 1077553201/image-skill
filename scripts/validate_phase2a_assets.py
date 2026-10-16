"""核验已有真实抠图资产；不执行模型、不修改审核状态。"""
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from product_studio.segmentation.pipeline import load_result
from product_studio.core.asset_binding import file_sha256


def main():
    records=[]
    for path in sorted((ROOT/'data/intermediate/phase2a').glob('*/segmentation_result.json')):
        _,result=load_result(path)
        with Image.open(result['source']['path']) as source:
            rgb=np.asarray(source.convert('RGB'));profile=source.info.get('icc_profile')
        with Image.open(path.parent/'product_rgba.png') as output:
            rgba=np.asarray(output);output_profile=output.info.get('icc_profile')
        with Image.open(path.parent/'alpha_mask.png') as mask: alpha=np.asarray(mask)
        x,y,w,h=result['roi'];outside=alpha.copy();outside[y:y+h,x:x+w]=0
        checks={'rgb_exact':bool(np.array_equal(rgb,rgba[:,:,:3])),
                'alpha_exact':bool(np.array_equal(alpha,rgba[:,:,3])),
                'outside_roi_zero':not bool(np.any(outside)),
                'icc_preserved':profile==output_profile,
                'rgba_hash_valid':file_sha256(path.parent/'product_rgba.png')==result['binding']['rgba_sha256'],
                'review_pending':result['human_review']['status']=='pending'}
        records.append({'case':path.parent.name,'result':str(path),'checks':checks})
    report={'scope':'asset integrity, NOT semantic mask accuracy','records':records,
            'all_checks_pass':all(all(r['checks'].values()) for r in records)}
    (ROOT/'reports/phase2a_asset_integrity.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'assets':len(records),'all_checks_pass':report['all_checks_pass']}))
    return 0 if report['all_checks_pass'] else 1


if __name__=='__main__':raise SystemExit(main())
