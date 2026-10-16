"""Campaign input and image-capable Agent handoff; no category guesses or per-SKU rules."""
from copy import deepcopy
from pathlib import Path
import re

from product_studio.core.schemas import Evidence, EvidenceStatus
from product_studio.creative.planning import validate_facts


class NeedsAnalysis(RuntimeError):
    pass


def campaign_request(raw):
    if not isinstance(raw,dict):raise ValueError('Request must be an object')
    r=deepcopy(raw)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}',r.get('product_id','')):
        raise ValueError('product_id must be a safe identifier')
    if bool(r.get('product_image'))==bool(r.get('product_asset')):
        raise ValueError('Provide exactly one product_image or product_asset')
    defaults={'product_category':None,'product_facts':{},'reference_url':None,'reference_images':[],
              'style_preference':{},'platform':'generic','language':'en','output_count':6,
              'output_sizes':{'default':[1024,1024],'wide_banner':[1536,864]},
              'creation_modes':['evidence_preserving'],'generation_budget':{'max_new_backgrounds':2},
              'review_policy':{'mode':'auto'},'scene':{'level':2,'presentation':'editorial_panel'}}
    for k,v in defaults.items():
        if r.get(k) is None:r[k]=deepcopy(v)
    for key in ('product_facts','style_preference','output_sizes','generation_budget','review_policy','scene'):
        if not isinstance(r[key],dict):raise ValueError(key+' must be an object')
    r['output_sizes']={**defaults['output_sizes'],**r['output_sizes']}
    r['generation_budget'].setdefault('max_new_backgrounds',2)
    if r['platform'] not in ('amazon','ebay','generic','social'):raise ValueError('Unsupported platform preset')
    if r['language'] not in ('en','zh'):raise ValueError('MVP supports en or zh; Agent supplies corresponding copy')
    if type(r['output_count']) is not int or not 1<=r['output_count']<=11:raise ValueError('output_count must be 1..11')
    if not r['creation_modes'] or not set(r['creation_modes'])<= {'evidence_preserving','concept_creative'}:
        raise ValueError('Invalid creation_modes')
    if r['review_policy'].get('mode','auto') not in ('auto','strict','preview'):raise ValueError('Invalid review mode')
    budget=r['generation_budget'].get('max_new_backgrounds',2)
    if type(budget) is not int or not 0<=budget<=3:raise ValueError('MVP budget is 0..3 new backgrounds')
    for size in r['output_sizes'].values():
        if not isinstance(size,list) or len(size)!=2 or any(type(v) is not int or v<512 or v>3072 or v%8 for v in size):
            raise ValueError('Output sizes must be 512..3072 pixels, multiples of 8')
    if 'default' not in r['output_sizes']:raise ValueError('output_sizes needs default')
    if not isinstance(r['product_facts'],dict):raise ValueError('product_facts must be an object')
    return r


def validate_understanding(analysis,binding,shape):
    if analysis.get('schema_version')!='product_understanding.4b.1' or analysis.get('provider')!='image_capable_agent':
        raise ValueError('Need an honestly declared image-capable Agent analysis')
    for key in ('source_id','instance_id','source_sha256','mask_version'):
        if analysis['binding'].get(key)!=binding[key]:raise ValueError('Agent analysis is bound to another asset/version: '+key)
    if not analysis.get('image_read_tool') or not analysis.get('visible_view') or not analysis.get('display_name'):
        raise ValueError('Missing actual image observation declaration/view/name')
    for name,raw in analysis.get('facts',{}).items():
        evidence=Evidence(**{**raw,'status':EvidenceStatus(raw['status']),'sources':tuple(raw.get('sources',[]))})
        if evidence.status not in (EvidenceStatus.OBSERVED,EvidenceStatus.UNKNOWN):
            raise ValueError('Agent-only facts cannot self-promote to human_verified')
        if evidence.sources and set(evidence.sources)!={binding['source_id']}:raise ValueError('Cross-source visual fact')
        if evidence.status!=EvidenceStatus.UNKNOWN and analysis.get('fact_kinds',{}).get(name) in ('performance','compatibility','certification','capacity','material_composition'):
            raise ValueError('Non-visible claims need user evidence, not Agent visual inference')
    for detail in analysis.get('detail_regions',[]):
        x,y,w,h=detail['bbox']
        if any(type(v) is not int for v in (x,y,w,h)) or min(x,y)<0 or min(w,h)<=0 or x+w>shape[1] or y+h>shape[0]:
            raise ValueError('Agent detail region is outside the source photo')
    return analysis


def organize_facts(request, analysis, binding):
    facts=deepcopy(analysis.get('facts',{}));provenance={k:{'kind':'agent_visible_observation','product_id':request['product_id'],'source_id':binding['source_id']} for k in facts}
    for key,entry in request['product_facts'].items():
        if not isinstance(entry,dict) or 'value' not in entry:raise ValueError('User facts require value/status/provenance, not implicit defaults')
        origin=entry.get('provenance',{})
        if origin.get('product_id')!=request['product_id']:raise ValueError('User fact belongs to another product')
        if entry.get('status')=='human_verified' and not (origin.get('kind')=='user_statement' and origin.get('statement') and entry.get('reviewer')):
            raise ValueError('Human facts require actual user statement and reviewer')
        facts[key]={k:v for k,v in entry.items() if k!='provenance'}
        facts[key]['sources']=[binding['source_id']] if entry['status']!='unknown' else []
        provenance[key]=origin
    for key in ('dimensions','weight','material','brand','compatibility','performance'):
        if key not in facts:facts[key]={'value':None,'status':'unknown','sources':[],'method':None}
    result={'schema_version':'product_claims.4a.1','binding':binding,'product_id':request['product_id'],
            'facts':facts,'provenance':provenance,'asset_human_review_status':'pending'}
    return validate_facts(result,binding)


def validate_agent_copy(analysis,facts):
    for feature in analysis.get('features',[]):
        if not feature.get('fact_ids'):raise ValueError('A feature needs sourced facts')
        for key in feature['fact_ids']:
            if key not in facts['facts'] or facts['facts'][key]['status']=='unknown':raise ValueError('Ungrounded feature copy')
    for intent,copy in analysis.get('copy',{}).items():
        for key in copy.get('fact_ids',[]):
            if key not in facts['facts'] or facts['facts'][key]['status']=='unknown':raise ValueError('Ungrounded creative copy: '+intent)
    return analysis
