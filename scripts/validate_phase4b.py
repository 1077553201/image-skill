"""Dataset acceptance driver; all product handling uses the same generic validator."""
from datetime import datetime,timezone
import argparse
import io
import json
from pathlib import Path
import re
import sys
import tempfile
import time
import unittest

from PIL import Image,ImageDraw,ImageFont,ImageOps

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from product_studio.core.asset_binding import file_sha256
from product_studio.creative.quality import validate_campaign
from product_studio.providers.comfyui import save_json


def run_tests():
    folder=ROOT/'reports/phase4b/test_tmp';folder.mkdir(exist_ok=True,parents=True)
    old=tempfile.tempdir;tempfile.tempdir=str(folder)
    try:
        suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
        stream=io.StringIO();start=time.monotonic();r=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        path=ROOT/f'reports/phase4b/tests_{stamp}.txt';path.write_text(stream.getvalue(),encoding='utf-8')
        result={'tests_run':r.testsRun,'original_tests':195,'new_tests':r.testsRun-195,'successful':r.wasSuccessful(),
                'failures':len(r.failures),'errors':len(r.errors),'skipped':len(r.skipped),'seconds':time.monotonic()-start,'log':str(path),
                'mock_unit_tests_are_separate_from_real_jobs':True}
        save_json(ROOT/'reports/phase4b/automated_tests.json',result)
        if not r.wasSuccessful():raise RuntimeError('Automated tests failed; see '+str(path))
        return result
    finally:tempfile.tempdir=old


def main():
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser();parser.add_argument('--remote',action='store_true');parser.add_argument('--run-tests',action='store_true')
    args=parser.parse_args()
    if args.run_tests:run_tests()
    read=lambda p:json.loads((ROOT/p).read_text(encoding='utf-8'))
    sets=[validate_campaign(ROOT,ROOT/path,remote=args.remote) for path in (
        'data/outputs/phase4b/bag_v2','data/outputs/phase4b/headphones_v2','data/outputs/phase4b/blue_left')]
    cold=validate_campaign(ROOT,ROOT/'data/outputs/phase4b/cold_start_watch',remote=False)
    cold_final=validate_campaign(ROOT,ROOT/'data/outputs/phase4b/cold_start_new_sku',remote=False)
    frozen=read('reports/phase4b/core_frozen_before_cold_start.json')
    changed=[p for p,h in frozen.items() if not (ROOT/p).is_file() or file_sha256(ROOT/p)!=h]
    current={str(p.relative_to(ROOT)) for folder in ('src','scripts','skills/universal-product-creative/scripts') for p in (ROOT/folder).rglob('*.py')}
    added=sorted(current-set(frozen))
    baseline=read('reports/phase4b/prior_asset_hashes.json')
    old_changed=[p for p,h in baseline.items() if not (ROOT/p).is_file() or file_sha256(ROOT/p)!=h]
    contamination=[]
    for report in sets:
        if report['product_id']=='blue_left':continue
        copy=' '.join(text for shot in report['images'] for text in shot['text'])
        if re.search(r'30\s*cm|500\s*g|composite',copy,re.I):contamination.append(report['product_id'])
    planned=[tuple(s['intents']) for s in sets]
    distinct=len(set(planned))==len(sets)
    tests=read('reports/phase4b/automated_tests.json')
    skills=read('reports/phase4b/skill_validation.json')
    cache=read('reports/phase4b/frozen_cli_smoke.json')
    passed=all(s['engineering_passed'] and s['image_count']>=6 for s in sets) and cold['engineering_passed'] and cold_final['engineering_passed'] and distinct and not contamination and not old_changed and not changed and not added and tests['successful'] and skills['valid'] and cache['all_cli_runs_succeeded']
    # Contact sheet compares one row per real campaign, with each campaign's own number of shots.
    canvas=Image.new('RGB',(1680,1040),'#e8ecef');draw=ImageDraw.Draw(canvas)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',20)
    for row,report in enumerate(sets):
        draw.text((15,row*345+8),f"{report['product_id']} | {report['mode']} | {report['style']} | final review pending",fill='#20303a',font=font)
        for column,shot in enumerate(report['images']):
            with Image.open(shot['image']) as im:thumb=ImageOps.contain(im.convert('RGB'),(230,265))
            x=column*240;y=row*345+42;canvas.paste(thumb,(x+(240-thumb.width)//2,y+(265-thumb.height)//2))
            draw.text((x+5,row*345+310),shot['shot_id'].split('_',1)[1],fill='#20303a',font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',14))
    canvas.save(ROOT/'reports/phase4b_comparison.png')
    report={'schema_version':'phase4b_validation.1','checked_at':datetime.now(timezone.utc).isoformat(),'engineering_passed':passed,
            'stage_acceptance':'pending_user_visual_review','same_entrypoint':'scripts/generate_product_campaign.py --request <data.json>',
            'finished_real_images':sum(s['image_count'] for s in sets),'campaigns':sets,'cold_start':cold_final,'additional_watch_cold_start':cold,
            'plans_have_different_intents':distinct,'cross_product_claim_contamination':contamination,
            'source_code_frozen_during_cold_start':not changed and not added,'changed_core_files':changed,'added_core_files':added,
            'preserved_prior_assets':len(baseline),'changed_prior_assets':old_changed,'tests':tests,'skill_validation':skills,'frozen_cli_smoke':cache,
            'actual_remote_generation_tasks':sum(len(s['jobs']) for s in sets),'mock_generation_not_counted':True,
            'limitations':['Agent visual analysis and original copy remain external Agent steps; no unattended Agent runtime deployed',
                'Masks for bag, headphones and watch remain preview; only current blue mask is strict',
                'Level 2 is a clearly framed environmental advertisement, not a physical installation photograph',
                'Level 3 person interactions are interface-only; no wearing/holding generated',
                'Automatic tests cannot establish all semantics, edge perfection, brand absence or platform eligibility',
                'Local fashion reference is a prior own AI-background composite, not a newly fetched fashion brand campaign']}
    save_json(ROOT/'reports/phase4b_validation.json',report)
    if not passed:raise RuntimeError('Phase 4B engineering validation failed; inspect report')
    print(f"{report['finished_real_images']} real cross-category images + {cold['image_count']+cold_final['image_count']} cold-start images; {tests['tests_run']} tests passed; user review pending")


if __name__=='__main__':main()
