"""Portable, hash-checked single-instance assets. Relocation is not a new review."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

from product_studio.core.asset_binding import file_sha256
from product_studio.providers.comfyui import save_json


def export_asset(result_path, output):
    from product_studio.generation.compositor import load_foreground
    result_path=Path(result_path).resolve();out=Path(output).resolve()
    raw=json.loads(result_path.read_text(encoding='utf-8'))
    _,result,gate=load_foreground(result_path,mode='preview',expected_instance=raw['instance_id'])
    if out.exists() and any(out.iterdir()):raise ValueError('Asset export directory must be empty')
    out.mkdir(parents=True,exist_ok=True)
    spec=json.loads((result_path.parent/'product_spec.json').read_text(encoding='utf-8'))
    source=next(s for s in spec['source_images'] if s['source_id']==result['binding']['source_id'])
    inputs={str(result_path):'segmentation_result.json',str(result_path.parent/'product_spec.json'):'product_spec.json',
            str(Path(source['path']).resolve()):'source_original'+Path(source['path']).suffix.lower(),
            str(result_path.parent/'alpha_mask.png'):'alpha_mask.png',str(result_path.parent/'product_rgba.png'):'product_rgba.png'}
    def evidence_paths(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in {'confirmation_record','review_record'} and isinstance(item,str):
                    path=Path(item).resolve()
                    if not path.is_file():raise ValueError('Required review evidence missing: '+str(path))
                    inputs[str(path)]='evidence/'+file_sha256(path)[:16]+'_'+path.name
                else:evidence_paths(item)
        elif isinstance(value,list):
            for item in value:evidence_paths(item)
    evidence_paths(spec)
    for old,name in inputs.items():
        dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(old,dest)
    manifest={'schema_version':'product_asset_bundle.4c.1','binding':result['binding'],
              'product_id':spec['product_id'],'files':{name:file_sha256(out/name) for name in inputs.values()},
              'path_relocations':inputs,'mask_review_valid_at_export':gate['mask_review_valid'],
              'review_semantics':'Existing exact source/instance/mask review only; export grants no approval'}
    save_json(out/'asset_bundle.json',manifest)
    return manifest


def import_asset(bundle_path, output):
    bundle_path=Path(bundle_path).resolve();out=Path(output).resolve()
    manifest=json.loads(bundle_path.read_text(encoding='utf-8'))
    if manifest.get('schema_version')!='product_asset_bundle.4c.1':raise ValueError('Unsupported asset bundle')
    root=bundle_path.parent
    for name,sha in manifest['files'].items():
        p=(root/name).resolve()
        if root not in p.parents or file_sha256(p)!=sha:raise ValueError('Bundle path/hash violation')
    if not set(manifest['path_relocations'].values())<=set(manifest['files']):
        raise ValueError('Every relocated path must name a hash-checked bundle member')
    out.mkdir(parents=True,exist_ok=True)
    if any(out.iterdir()):
        prior=out/'bundle_import.json'
        if prior.is_file() and json.loads(prior.read_text(encoding='utf-8'))['bundle_sha256']==file_sha256(bundle_path):
            return out/'segmentation_result.json'
        raise ValueError('Import output already contains a different asset')
    replacements={old:str((out/name).resolve()) for old,name in manifest['path_relocations'].items()}
    def relocate(value):
        if isinstance(value,dict):return {k:relocate(v) for k,v in value.items()}
        if isinstance(value,list):return [relocate(v) for v in value]
        return replacements.get(value,value) if isinstance(value,str) else value
    for name in manifest['files']:
        dest=out/name;dest.parent.mkdir(parents=True,exist_ok=True)
        if name in {'segmentation_result.json','product_spec.json'}:
            save_json(dest,relocate(json.loads((root/name).read_text(encoding='utf-8'))))
        else:shutil.copyfile(root/name,dest)
    result_path=out/'segmentation_result.json'
    result=json.loads(result_path.read_text(encoding='utf-8'))
    for key in ('source_id','source_sha256','instance_id','roi','mask_version','mask_sha256','rgba_sha256'):
        if result['binding'].get(key)!=manifest['binding'].get(key):raise ValueError('Bundle identity mismatch: '+key)
    for name in result.get('artifacts',{}):
        current=out/name
        if current.is_file():result['artifacts'][name]=file_sha256(current)
    result['portable_import']={'bundle_sha256':file_sha256(bundle_path),'operation':'path relocation only; original JSON hashes in bundle_import.json'}
    save_json(result_path,result)
    # Original review bytes are immutable. Their file paths are audit context;
    # review validity is bound to the same hashes, instance and version.
    save_json(out/'bundle_import.json',{'bundle_sha256':file_sha256(bundle_path),'binding':manifest['binding'],
              'path_relocations':replacements,'original_record_hashes':manifest['files'],'new_review_created':False})
    from product_studio.generation.compositor import load_foreground
    _,_,gate=load_foreground(out/'segmentation_result.json',mode='preview',expected_instance=manifest['binding']['instance_id'])
    if gate['mask_review_valid']!=manifest['mask_review_valid_at_export']:raise ValueError('Review validity changed during relocation')
    return out/'segmentation_result.json'
