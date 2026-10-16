"""Resumable universal campaign entrypoint. Agent supplies observations, not Python code."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys

from product_studio.core.asset_binding import file_sha256
from product_studio.creative.campaign import campaign_request, NeedsAnalysis, organize_facts, validate_understanding, validate_agent_copy
from product_studio.creative.intents import select_intents, catalog, scene_gate
from product_studio.creative.layouts import compile_layout
from product_studio.generation.compositor import load_foreground
from product_studio.generation.candidates import canonical, BackgroundCache
from product_studio.generation.marketing_renderer import render_set
from product_studio.providers.comfyui import ComfyUIProvider, digest, save_json
from product_studio.references.analysis import validate_analysis
from product_studio.references.sources import collect


def resolve(root,path):
    return (Path(root)/path).resolve()


def _references(root,request,out):
    if request.get('reference_catalog'):
        path=resolve(root,request['reference_catalog'])
        cat=json.loads(path.read_text(encoding='utf-8'))
        analysis_path=request.get('reference_analysis')
        if not analysis_path:raise NeedsAnalysis('Collected references require actual Agent reference_analysis')
        analysis_path=resolve(root,analysis_path)
        validate_analysis(cat,json.loads(analysis_path.read_text(encoding='utf-8')))
        return path,analysis_path
    if request.get('reference_url') or request.get('reference_images'):
        folder=root/'data/references'/('campaign_'+request['product_id']+'_'+digest(canonical([request['reference_url'],request['reference_images']]))[:12])
        catalog_path=folder/'catalog.json'
        if not catalog_path.exists():
            if request.get('reference_url'):
                collect(folder,url=request['reference_url'])
            else:
                sources=request['reference_images']
                sources=[sources] if isinstance(sources,str) else sources
                merged={'schema_version':'reference.4a.1','assets':[],'source':{'kind':'user_local_collection'},'missing_assets':[]}
                for i,path in enumerate(sources):
                    partial=collect(folder/f'source_{i}',local=resolve(root,path))
                    for asset in partial['assets']:
                        asset['asset_id']='ref_'+str(len(merged['assets'])+1).zfill(2);merged['assets'].append(asset)
                save_json(catalog_path,merged)
        raise NeedsAnalysis('Real reference catalog collected at '+str(catalog_path)+'; Agent must read images and supply reference_catalog/reference_analysis')
    folder=out/'evidence';folder.mkdir(exist_ok=True)
    cat=folder/'no_reference.json';analysis=folder/'original_direction.json'
    if not cat.exists():save_json(cat,{'assets':[],'status':'no_reference_requested','not_a_reference_analysis':True})
    if not analysis.exists():save_json(analysis,{'provider':'original_agent_direction','reference_images_analyzed':0,'not_a_reference_analysis':True})
    return cat,analysis


def _asset(root,request,out,*,portable=False):
    if request.get('product_asset'):
        asset=request['product_asset'];asset=asset['segmentation_result'] if isinstance(asset,dict) else asset
        path=resolve(root,asset)
        if path.name=='asset_bundle.json':
            from product_studio.asset_bundle import import_asset
            return import_asset(path,out/'selected_asset')
        return path
    image=resolve(root,request['product_image']);selection=request.get('instance_selection',{})
    target=out/'selected_asset/segmentation_result.json'
    if target.exists():return target
    if not selection.get('roi') and selection.get('single_instance') is not True:
        raise NeedsAnalysis('Agent/user must explicitly select an instance ROI or declare single_instance; multiple objects are not merged automatically')
    if portable:
        import os
        from PIL import Image
        from product_studio.segmentation.pipeline import segment
        from product_studio.segmentation.provider import BiRefNetLiteProvider
        model=request.get('segmentation_model') or os.environ.get('PRODUCT_STUDIO_SEGMENTATION_MODEL')
        if not model:raise ValueError('Raw image segmentation requires explicit PRODUCT_STUDIO_SEGMENTATION_MODEL or segmentation_model; weights are not bundled')
        with Image.open(image) as im:roi=selection.get('roi') or [0,0,*im.size]
        segment(image,tuple(roi),request['product_id'],target.parent,BiRefNetLiteProvider(resolve(root,model)))
        return target
    python=request.get('segmentation_python')
    if python:python=resolve(root,python)
    else:
        local=root/'.venv-seg/Scripts/python.exe';python=local if local.exists() else Path(sys.executable)
    args=[str(python),str(root/'scripts/segment_product.py'),'segment',str(image),'--instance-id',request['product_id'],'--output-dir',str(target.parent)]
    args += ['--roi',*[str(v) for v in selection['roi']]] if selection.get('roi') else ['--single-instance']
    result=subprocess.run(args,cwd=root,capture_output=True,text=True,encoding='utf-8',errors='replace')
    save_json(out/'segmentation_execution.json',{'command':args,'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'reused_existing_segmentation_CLI':True})
    if result.returncode!=0:raise RuntimeError('Existing segmentation CLI did not pass: '+result.stdout+result.stderr)
    return target


def _style(root,request,analysis):
    style=deepcopy(analysis.get('style',{}));style.update(request.get('style_preference',{}))
    neutral={'paper':'#f5f5f3','white':'#ffffff','ink':'#20272c','muted':'#505c65',
             'navy':'#27303b','blue':'#5d6269','cyan':'#c7cbcf','line':'#b6bcc2'}
    style['palette']={**neutral,**style.get('palette',{})}
    style.setdefault('background_briefs',{})
    for key in ('paper','white','ink','muted','navy','blue','cyan','line'):
        if not re.fullmatch(r'#[0-9a-fA-F]{6}',style['palette'].get(key,'')):raise ValueError('Missing/invalid style color: '+key)
    from product_studio.configuration import available_font
    if not style.get('font_regular'):style['font_regular']=available_font(request['language'])
    if not style.get('font_bold'):style['font_bold']=available_font(request['language'],bold=True)
    style.setdefault('safe_margin_px',40)
    for key in ('font_regular','font_bold'):
        if not resolve(root,style[key]).is_file():raise ValueError('Configure an available local font: '+style[key])
        style[key]=str(resolve(root,style[key]))
    style.setdefault('excluded_copy_tokens',analysis.get('excluded_copy_tokens',[]))
    style['production_disclosure']=request.get('production_disclosure')
    return style


def build_plan(root,request,out,asset,rgba,result,gate,analysis,ref_paths):
    validate_understanding(analysis,result['binding'],rgba.shape)
    from product_studio.creative.facts import resolve_product_facts
    from product_studio.creative.content_contract import task_contract
    analysis=task_contract(request,analysis)
    facts=resolve_product_facts(asset,request,analysis,result['binding']);validate_agent_copy(analysis,facts)
    evidence=out/'evidence';evidence.mkdir(exist_ok=True)
    for filename,value in [('product_facts.json',facts),('agent_analysis.json',analysis)]:
        path=evidence/filename
        if path.exists() and json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('Evidence changed; create a new campaign revision')
        if not path.exists():save_json(path,value)
    style=_style(root,request,analysis)
    from product_studio.core.task_planner import generation_route
    route=generation_route('background_only','strict_product' if gate['mode']=='strict' else 'source_preserving_preview',mask_review_valid=gate['mask_review_valid'])
    intents,decisions=select_intents(request,facts,analysis)
    needed=set()
    if any(i in ('studio_photo','brand_signature','editorial_campaign','wide_banner') for i in intents):needed.add('studio')
    if 'lifestyle_scene' in intents:needed.add('environment')
    max_new=request['generation_budget']['max_new_backgrounds']
    backgrounds={}
    for role in sorted(needed):
        brief=style['background_briefs'].get(role)
        if not brief or not brief.get('prompt'):raise NeedsAnalysis('Agent needs actual independent '+role+' background prompt')
        seed=int(digest(canonical([request['product_id'],result['binding'],style.get('name'),role,brief]))[:8],16)
        backgrounds[role]={'width':1024,'height':1024,'seed':seed,'prompt':brief['prompt'],
                           'negative':brief.get('negative','product, logo, text, duplicate merchandise, watermark')}
    shots=[compile_layout(i,n,request,analysis,facts,rgba,style,backgrounds) for n,i in enumerate(intents)]
    from product_studio.creative.director import repetition_risks
    diversity=repetition_risks(shots)
    vocabulary=' '.join(n['text'] for s in shots for n in s['text'])
    style['copy_vocabulary']=sorted(set(re.findall(r'[A-Za-z]+',vocabulary)))
    style['vocabulary_note']='Agent-authored copy vocabulary, not an independent general dictionary'
    facts_path=evidence/'product_facts.json';cat,ref_analysis=ref_paths
    return {'schema_version':'campaign_plan.4c.1','product_id':request['product_id'],'instance_id':result['instance_id'],
            'mode':gate['mode'],'source_result':str(asset),'source_binding':result['binding'],'review_gate':gate,
            'facts_path':str(facts_path),'facts_sha256':file_sha256(facts_path),
            'reference_catalog':str(cat),'reference_catalog_sha256':file_sha256(cat),
            'analysis_path':str(ref_analysis),'analysis_sha256':file_sha256(ref_analysis),
            'agent_analysis_path':str(evidence/'agent_analysis.json'),'agent_analysis_sha256':file_sha256(evidence/'agent_analysis.json'),
            'analysis_provider':'image_capable_agent','style':style,'shots':shots,'backgrounds':backgrounds,
            'output_dir':str(out),'max_new_generation_tasks':max_new,'intent_decisions':decisions,
            'scene_gate':scene_gate(request['scene'],request['creation_modes']),
            'reference_pixels_allowed_as_layers':False,'asset_human_review_status':'pending','request':request,
            'task_intent_contract':analysis['task_intent_contract'],'internal_notes':analysis['internal_notes'],'creative_diversity':diversity,
            'generation_route':route,'agent_input_sha256':file_sha256(resolve(root,request['agent_analysis'])),
            'provenance':{'inherited_fact_ids':facts['inherited_fact_ids'],'canonical_product_id':facts['canonical_product_id']}}


def execute(root,request_path,*,prepare_only=False,render_only=False,provider=None,output_dir=None,portable=False,config_dir=None):
    root=Path(root).resolve();raw_request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    if portable and 'scene' not in raw_request:raw_request['scene']={'level':1}
    request=campaign_request(raw_request)
    if portable:request.setdefault('creative_direction',{'enabled':True})
    if portable and not output_dir and not request.get('output_dir'):raise ValueError('Installed engine requires an explicit --output or output_dir')
    out=resolve(root,output_dir or request.get('output_dir') or 'data/outputs/campaigns/'+request['product_id']+'_'+digest(canonical(request))[:12])
    allowed=(root/'data/outputs').resolve()
    if not portable and (out==allowed or allowed not in out.parents):raise ValueError('Campaign output must be a child of project data/outputs')
    out.mkdir(parents=True,exist_ok=True)
    snapshot=out/'campaign_request.json'
    if snapshot.exists() and json.loads(snapshot.read_text(encoding='utf-8'))!=request:
        old=json.loads(snapshot.read_text(encoding='utf-8'))
        handoff_keys={'agent_analysis','reference_catalog','reference_analysis','instance_selection'}
        stable=lambda r:{k:v for k,v in r.items() if k not in handoff_keys}
        state_path=out/'execution_state.json'
        paused=state_path.exists() and json.loads(state_path.read_text(encoding='utf-8')).get('status')=='needs_agent_analysis'
        if not paused or (out/'creative_plan.json').exists() or stable(old)!=stable(request):
            raise ValueError('Request changed; use a new output revision')
        save_json(out/('request_before_handoff_'+digest(canonical(old))[:12]+'.json'),old)
        save_json(snapshot,request)
    if not snapshot.exists():save_json(snapshot,request)
    state={'product_id':request['product_id'],'request_path':str(Path(request_path).resolve()),'output':str(out),'status':'preparing'}
    try:
        asset=_asset(root,request,out,portable=portable)
        raw=json.loads(asset.read_text(encoding='utf-8'));instance=raw['instance_id']
        rgba,result,gate=load_foreground(asset,mode='preview',expected_instance=instance)
        mode=request['review_policy'].get('mode','auto')
        mode=('strict' if gate['mask_review_valid'] else 'preview') if mode=='auto' else mode
        rgba,result,gate=load_foreground(asset,mode=mode,expected_instance=instance)
        state.update(source_binding=result['binding'],mode=mode)
        refs=_references(root,request,out)
        if not request.get('agent_analysis'):
            spec=json.loads((asset.parent/'product_spec.json').read_text(encoding='utf-8'))
            source=next(s for s in spec['source_images'] if s['source_id']==result['binding']['source_id'])
            from product_studio.creative.facts import resolve_product_facts
            current_facts=resolve_product_facts(asset,request,{},result['binding'])
            import numpy as np
            from PIL import Image
            yy,xx=np.indices(rgba.shape[:2]);checker=np.where(((xx//24+yy//24)%2)[...,None],190,230)
            a=rgba[:,:,3:4].astype(np.float32)/255
            preview=out/'selected_instance_preview.png'
            Image.fromarray(np.rint(rgba[:,:,:3]*a+checker*(1-a)).astype(np.uint8)).save(preview)
            save_json(out/'agent_handoff.json',{'schema_version':'campaign_handoff.4b.1','binding':result['binding'],
                'source_asset':str(asset),'source_image':str(resolve(root,source['path'])),
                'selected_instance_preview':str(preview),'selected_roi_source_pixels':result['binding']['roi'],
                'reference_catalog':str(refs[0]),'needed':'Image-capable Agent must actually read source/reference images and return product_understanding.4b.1 facts, visible view, copy, real detail regions and style. Do not infer from category/file name.',
                'current_product_facts':current_facts,'confirmed_fact_ids':current_facts['inherited_fact_ids'],
                'fact_precedence':'Human confirmations for this exact source/instance/version cannot be downgraded by Agent guesses',
                'asset_human_review_status':'pending'})
            raise NeedsAnalysis('Awaiting image-capable Agent; see agent_handoff.json')
        analysis=json.loads(resolve(root,request['agent_analysis']).read_text(encoding='utf-8'))
        plan=build_plan(root,request,out,asset,rgba,result,gate,analysis,refs)
        plan_path=out/'creative_plan.json'
        if plan_path.exists() and json.loads(plan_path.read_text(encoding='utf-8'))!=plan:raise ValueError('Plan changed; retain prior output and create a new revision')
        if not plan_path.exists():save_json(plan_path,plan)
        save_json(out/'shot_type_catalog.json',catalog())
        state['status']='planned';save_json(out/'execution_state.json',state)
        if prepare_only:return state
        tasks=[{'instance_id':instance,'candidate_id':name,'source_binding':result['binding'],'mode':mode,**settings} for name,settings in plan['backgrounds'].items()]
        cache=None
        if tasks:
            if portable and not request.get('comfyui_config') and provider is None:
                from product_studio.configuration import provider_config
                config=provider_config(config_dir,out)
            else:config=resolve(root,request.get('comfyui_config','configs/comfyui_phase3a.json'))
            provider=provider or ComfyUIProvider(config,project_root=root)
            cache_root=resolve(root,request['reuse_backgrounds_from'])/'background_tasks' if request.get('reuse_backgrounds_from') else out/'background_tasks'
            if not portable and (root/'data/outputs').resolve() not in cache_root.resolve().parents:raise ValueError('Reused background cache must be inside project outputs')
            cache=BackgroundCache(provider,cache_root)
        new=sum(not (cache.root/cache.key(t)/'request.json').exists() for t in tasks)
        if new>plan['max_new_generation_tasks']:raise ValueError('New background task budget exceeded before submission')
        records=[]
        for task in tasks:
            if render_only and not (cache.root/cache.key(task)/'request.json').exists():raise RuntimeError('render-only cannot submit new tasks')
            image,execution,info=cache.get(task)
            records.append({'background_id':task['candidate_id'],'path':str(image),'execution':execution,'cache':info,'status':'succeeded'})
            save_json(out/'background_manifest.json',{'records':records,'automatic_retries':0,'product_id':request['product_id']})
        if not tasks:save_json(out/'background_manifest.json',{'records':[],'no_AI_backgrounds_requested':True})
        result=render_set(root,plan,out,records)
        state.update(status='rendered_pending_review',images=len(result['images']),new_background_tasks=new)
        return state
    except NeedsAnalysis as exc:
        state.update(status='needs_agent_analysis',reason=str(exc));return state
    except Exception as exc:
        state.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)});raise
    finally:
        state['updated_at']=datetime.now(timezone.utc).isoformat()
        save_json(out/'execution_state.json',state)
        history=out/'execution_history.jsonl'
        with history.open('a',encoding='utf-8') as f:f.write(json.dumps(state,ensure_ascii=False)+'\n')
