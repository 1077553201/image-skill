"""Single source of current, instance-bound product facts and confirmed evidence."""
from copy import deepcopy
import json
from pathlib import Path

from product_studio.core.asset_binding import file_sha256
from product_studio.creative.campaign import organize_facts
from product_studio.creative.planning import validate_facts


def resolve_product_facts(result_path,request,analysis,binding):
    path=Path(result_path).resolve();spec=json.loads((path.parent/'product_spec.json').read_text(encoding='utf-8'))
    from product_studio.segmentation.pipeline import load_result
    _,segmentation=load_result(path)
    for field in ('source_id','source_sha256','instance_id','roi','mask_version','mask_sha256','rgba_sha256'):
        if segmentation['binding'].get(field)!=binding.get(field):raise ValueError('Current fact source binding mismatch: '+field)
    source=next((s for s in spec['source_images'] if s['source_id']==binding['source_id']),None)
    if source is None:raise ValueError('Confirmed fact source is not in current product')
    if source['sha256']!=binding['source_sha256'] or file_sha256(source['path'])!=source['sha256'] or spec['selected_instance']!=binding['instance_id']:
        raise ValueError('Confirmed facts source/instance mismatch')
    current=spec['product_mask']['value']
    for key in ('source_id','source_sha256','instance_id','mask_version'):
        if current.get(key)!=binding[key]:raise ValueError('Confirmed facts mask binding mismatch: '+key)
    result=organize_facts(request,analysis,binding)
    inherited=[];decisions=[]
    for key,entry in spec.get('verified_facts',{}).items():
        if key=='product_mask' or entry.get('status')!='human_verified':continue
        value=entry.get('value');record=None
        if set(entry.get('sources',[]))!={binding['source_id']} or not entry.get('reviewer'):
            raise ValueError('Confirmed fact is not bound to current source/reviewer: '+key)
        if isinstance(value,dict):
            for field in ('source_id','source_sha256','instance_id'):
                if value.get(field)!=binding[field]:raise ValueError('Confirmed fact belongs to another instance: '+key)
            if value.get('confirmation_record'):
                record_path=Path(value['confirmation_record'])
                if file_sha256(record_path)!=value.get('confirmation_sha256'):raise ValueError('Confirmation record hash mismatch')
                record=json.loads(record_path.read_text(encoding='utf-8'))
                for field in ('source_id','source_sha256','instance_id'):
                    if record.get(field)!=binding[field]:raise ValueError('Review record belongs to another asset')
                if record.get('new_mask_version') and record['new_mask_version']!=binding['mask_version']:
                    raise ValueError('Confirmed fact references a different mask revision; explicitly reconcile before use')
                if record.get('reviewer')!=entry['reviewer']:raise ValueError('Confirmation reviewer mismatch')
        previous=result['facts'].get(key)
        if previous and previous['status']!='unknown' and previous['value']!=value:
            raise ValueError('Observation/request conflicts with human-confirmed fact: '+key)
        if previous and previous['status']=='unknown':decisions.append({'fact_id':key,'decision':'preserved_human_confirmation_over_agent_unknown'})
        result['facts'][key]=deepcopy(entry)
        result['provenance'][key]={'kind':'inherited_product_spec_confirmation','product_id':request['product_id'],
                'canonical_product_id':spec['product_id'],'source_id':binding['source_id'],'instance_id':binding['instance_id'],
                'source_sha256':binding['source_sha256'],'mask_version':binding['mask_version'],
                'product_spec_sha256':file_sha256(path.parent/'product_spec.json'),'reviewer':entry['reviewer'],
                'confirmation_record':value.get('confirmation_record') if isinstance(value,dict) else None,
                'confirmation_sha256':value.get('confirmation_sha256') if isinstance(value,dict) else None}
        inherited.append(key)
    result.update(canonical_product_id=spec['product_id'],inherited_fact_ids=inherited,resolution_decisions=decisions)
    return validate_facts(result,binding)
