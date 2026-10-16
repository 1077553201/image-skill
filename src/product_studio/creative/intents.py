"""Category-independent creative intents and implemented scene capabilities."""
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ShotType:
    name: str
    applicability: str
    required_assets: tuple[str, ...]
    required_facts: str
    strategy: str
    layout: str
    authenticity: str
    platforms: tuple[str, ...] = ('amazon_secondary', 'generic', 'social')
    fallback: str = 'editorial_campaign'


TYPES = {}


def register(shot_type):
    if shot_type.name in TYPES:
        raise ValueError('Duplicate creative intent')
    TYPES[shot_type.name] = shot_type


for spec in (
    ('white_hero','Any selected product','none','solid_white','centered'),
    ('studio_photo','Any selected product','none','independent_studio_background','centered'),
    ('brand_signature','Appearance or brand facts available','visible appearance','background_and_type','split'),
    ('feature_infographic','Sourced visible features or verified benefits','at least one grounded feature','factual_type','split'),
    ('material_detail','Actual visible crop is available','visible detail, material only if sourced','source_crop','detail_panes'),
    ('structure_explainer','Visible or confirmed structural features','structural facts','factual_type','title_above'),
    ('specifications','Sourced dimensions or specifications exist','quantity facts','factual_type','split'),
    ('lifestyle_scene','Compatible non-contact presentation','scene/view constraints','environment_editorial_panel','environment_panel'),
    ('editorial_campaign','Any selected product','appearance or neutral editorial copy','background_and_type','split'),
    ('wide_banner','Any selected product','appearance or neutral editorial copy','background_and_type','wide'),
    ('comparison','Explicit human-verified comparison dataset','comparison evidence','factual_type','split'),
):
    name, applies, facts, strategy, layout = spec
    register(ShotType(name, applies, ('bound_foreground',), facts, strategy, layout,
                      'Visible original pixels only; no hidden view or unsupported claim'))


def catalog():
    return {k:asdict(v) for k,v in TYPES.items()}


def scene_gate(scene, creation_modes):
    level=scene.get('level',1)
    if type(level) is not int or level not in (1,2,3):
        raise ValueError('Scene level must be 1, 2, or 3')
    if level==3:
        return {'allowed':False,'capability':'interface_only','route':'concept_creative' if 'concept_creative' in creation_modes else 'blocked',
                'reason':'Person interaction, wearing, holding and occlusion synthesis are not implemented; no reliable contact evidence is assumed'}
    if any(scene.get(k,False) for k in ('physical_contact','wearing','holding','occlusion')):
        return {'allowed':False,'route':'blocked','reason':'Contact/occlusion editing is not supported by the source-pixel compositor'}
    if level==2 and scene.get('presentation','editorial_panel')!='editorial_panel':
        return {'allowed':False,'route':'blocked','reason':'This MVP requires an explicit graphic panel over the environment, avoiding false perspective/contact'}
    return {'allowed':True,'route':'evidence_preserving','capability':'implemented',
            'level':level,'presentation':'editorial_panel' if level==2 else 'foreground_composite',
            'environment_physical_relationship_verified':False}


def eligible(intent, facts, analysis):
    known={k:v for k,v in facts['facts'].items() if v['status'] in ('observed','human_verified')}
    kinds=analysis.get('fact_kinds',{})
    if intent=='specifications':return any(kinds.get(k)=='quantity' for k in known), 'No sourced quantity specifications'
    if intent=='comparison':return any(kinds.get(k)=='comparison' and v['status']=='human_verified' for k,v in known.items()), 'No human-verified comparison dataset'
    if intent=='material_detail':return bool(analysis.get('detail_regions')), 'No actual source detail crop'
    if intent=='structure_explainer':return any(kinds.get(k)=='structure' for k in known), 'No visible/verified structural feature'
    if intent=='feature_infographic':return bool(analysis.get('features')), 'No grounded features'
    return True,''


def select_intents(request, facts, analysis):
    preferred=request.get('shot_types') or analysis.get('recommended_intents') or [
        'white_hero','studio_photo','feature_infographic','material_detail','lifestyle_scene','wide_banner']
    selected=[];decisions=[]
    for name in list(preferred)+list(TYPES):
        if name not in TYPES:raise ValueError('Unknown shot type: '+str(name))
        if name in selected:continue
        allowed,why=eligible(name,facts,analysis)
        if not allowed:
            decisions.append({'requested_intent':name,'status':'skipped_missing_evidence','reason':why,'fallback':TYPES[name].fallback})
            continue
        if name=='lifestyle_scene':
            gate=scene_gate(request.get('scene',{'level':2}),request['creation_modes'])
            if not gate['allowed']:
                decisions.append({'requested_intent':name,'status':'unsupported','scene_gate':gate})
                continue
        selected.append(name)
        if len(selected)==request['output_count']:break
    if len(selected)<request['output_count']:raise ValueError('Not enough supported distinct intents for requested count')
    return selected,decisions
