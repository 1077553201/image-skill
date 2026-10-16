"""Design-first handoff and scoped approvals. No generation side effects.

Revisions are complete immutable snapshots; the current pointer is replaceable.
Hashes detect accidental edits, not a substitute for authenticated user identity.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from .content_contract import validate_consumer_text

PAGE_FIELDS = '''page_id page_purpose key_message target_audience consumer_copy composition
product_position product_scale camera_angle focal_point background_description lighting_design
color_palette typography decorative_elements layer_structure required_assets image_generation_route
output_size fidelity_level quality_criteria'''.split()
STATES = ('intake', 'awaiting_answers', 'brief_ready', 'concepts_ready',
          'awaiting_concept_approval', 'page_design_ready', 'awaiting_design_approval',
          'generating', 'reviewing', 'revision_requested', 'delivered')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_page(page):
    missing = [key for key in PAGE_FIELDS if key not in page]
    if missing:
        raise ValueError(f'Missing PageDesign fields: {missing}')
    if not isinstance(page['page_id'], str) or not page['page_id']:
        raise ValueError('page_id must be nonempty')
    copy = page['consumer_copy']
    if not isinstance(copy, dict) or set(copy) - {'headline', 'body', 'eyebrow'}:
        raise ValueError('Only headline/body/eyebrow may enter consumer_copy')
    for text in copy.values():
        if not isinstance(text, str):
            raise ValueError('Consumer copy must be strings')
        validate_consumer_text(text)
    center = page['product_position']
    if len(center) != 2 or any(not 0 <= x <= 1 for x in center):
        raise ValueError('product_position must be normalized [x,y]')
    if not 0 < page['product_scale'] <= 1:
        raise ValueError('product_scale is fraction of canvas longest edge')
    if len(page['output_size']) != 2 or any(type(n) is not int or n <= 0 for n in page['output_size']):
        raise ValueError('Invalid output_size')
    if page['fidelity_level'] not in ('source_preserving_preview', 'strict_product', 'concept_creative'):
        raise ValueError('Invalid fidelity_level')
    if page['image_generation_route'] != 'background_only':
        raise ValueError('This design handoff currently supports background_only, not product editing')
    for box in page['composition']['text_regions']:
        if len(box) != 4 or any(not 0 <= x <= 1 for x in box) or box[0]+box[2] > 1 or box[1]+box[3] > 1:
            raise ValueError('Text regions must fit normalized canvas')


class DesignSession:
    def __init__(self, directory):
        self.root = Path(directory)

    def load(self):
        pointer = json.loads((self.root / 'session.json').read_text(encoding='utf-8'))
        revision = self.root / 'revisions' / f"{pointer['revision']:04d}.json"
        data = json.loads(revision.read_text(encoding='utf-8'))
        if digest(data) != pointer['sha256']:
            raise ValueError('Session snapshot hash mismatch')
        # Verify every parent before trusting an approval inherited from history.
        current = data
        for number in range(pointer['revision']-1, 0, -1):
            parent = json.loads((self.root/'revisions'/f'{number:04d}.json').read_text(encoding='utf-8'))
            if digest(parent) != current['parent_sha256']:
                raise ValueError('Session history hash mismatch')
            current = parent
        return data

    def _save(self, data, action, actor, statement):
        if not actor or not statement:
            raise ValueError('Actor and evidence statement required')
        previous = self.load() if (self.root/'session.json').exists() else None
        data = deepcopy(data)
        data['revision'] = previous['revision']+1 if previous else 1
        data['parent_sha256'] = digest(previous) if previous else None
        data['event'] = {'action': action, 'actor': actor, 'statement': statement,
                         'recorded_at': now()}
        folder = self.root/'revisions'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder/f"{data['revision']:04d}.json"
        # Exclusive create protects old versions; use one writer per session.
        with path.open('x', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
        temp = self.root/'session.tmp'
        temp.write_text(json.dumps({'revision': data['revision'], 'sha256': digest(data)}), encoding='utf-8')
        temp.replace(self.root/'session.json')
        return data

    def create(self, binding, actor, statement):
        if (self.root/'session.json').exists():
            raise ValueError('Session already exists')
        required = {'source_id', 'source_sha256', 'instance_id', 'mask_version', 'mask_sha256', 'rgba_sha256'}
        if not required <= binding.keys() or not all(binding[k] for k in required):
            raise ValueError('Complete source/instance/mask binding required')
        return self._save({'schema_version':'design_session.1', 'state':'intake',
                           'binding': binding, 'artifacts':{}, 'concept_approval':None,
                           'page_approvals':{}}, 'create', actor, statement)

    def put(self, kind, value, actor='agent', statement='Design artifact prepared'):
        data = self.load()
        if kind not in ('creative_brief', 'product_analysis', 'reference_analysis', 'creative_concepts', 'page_designs'):
            raise ValueError('Unknown artifact')
        artifacts = data['artifacts']
        if kind == 'creative_brief':
            required = {'user_requirements', 'verified_product_facts', 'visual_observations',
                        'design_recommendations', 'unknown_properties', 'blocking_questions'}
            if not required <= value.keys():
                raise ValueError('Brief evidence channels are required')
        if kind == 'creative_concepts':
            if not all(k in artifacts for k in ('creative_brief', 'product_analysis', 'reference_analysis')):
                raise ValueError('Brief and actual research required before concepts')
            ids = [c['concept_id'] for c in value['concepts']]
            if not 2 <= len(ids) <= 3 or len(set(ids)) != len(ids):
                raise ValueError('Provide 2–3 distinct concept IDs')
        if kind == 'page_designs':
            self._require_concept(data)
            if value.get('concept_id', data['concept_approval']['concept_id']) != data['concept_approval']['concept_id']:
                raise ValueError('Page designs belong to another concept')
            pages = value['pages']
            for page in pages:
                validate_page(page)
                for asset in page['required_assets']:
                    if 'binding' in asset and asset['binding'] != data['binding']:
                        raise ValueError('Page asset belongs to another instance/version')
            if not pages or len({p['page_id'] for p in pages}) != len(pages):
                raise ValueError('Pages must have unique IDs')
            old = {p['page_id']:p for p in artifacts.get(kind, {}).get('pages', [])}
            new = {p['page_id']:p for p in pages}
            data['page_approvals'] = {pid:a for pid,a in data['page_approvals'].items()
                if pid in new and digest(old.get(pid)) == digest(new[pid])}
        elif artifacts.get(kind) != value:
            data['concept_approval'] = None
            data['page_approvals'] = {}
            artifacts.pop('page_designs', None)
        artifacts[kind] = deepcopy(value)
        if artifacts.get('creative_brief', {}).get('blocking_questions'):
            data['state'] = 'awaiting_answers'
        elif kind == 'page_designs':
            data['state'] = 'awaiting_design_approval'
        elif 'creative_concepts' in artifacts:
            data['state'] = 'awaiting_concept_approval'
        elif 'creative_brief' in artifacts:
            data['state'] = 'awaiting_answers' if artifacts['creative_brief']['blocking_questions'] else 'brief_ready'
        return self._save(data, f'put:{kind}', actor, statement)

    @staticmethod
    def _context(data):
        return digest({'binding':data['binding'], 'artifacts':{k:v for k,v in data['artifacts'].items() if k != 'page_designs'}})

    def _require_concept(self, data):
        approval = data['concept_approval']
        if not approval or approval['context_sha256'] != self._context(data):
            raise ValueError('Current concept must be approved first')

    def approve_concept(self, concept_id, reviewer, statement):
        data = self.load()
        if data['artifacts']['creative_brief']['blocking_questions']:
            raise ValueError('Resolve blocking intake questions first')
        if concept_id not in [c['concept_id'] for c in data['artifacts']['creative_concepts']['concepts']]:
            raise ValueError('Unknown concept')
        if data['concept_approval'] and data['concept_approval']['concept_id'] != concept_id:
            data['artifacts'].pop('page_designs', None)
            data['page_approvals'] = {}
        data['concept_approval'] = {'concept_id':concept_id, 'reviewer':reviewer,
            'user_statement':statement, 'recorded_at':now(), 'scope':'concept_only',
            'context_sha256':self._context(data)}
        data['state'] = 'awaiting_design_approval' if 'page_designs' in data['artifacts'] else 'concepts_ready'
        return self._save(data, 'approve_concept', reviewer, statement)

    def approve_page(self, page_id, reviewer, statement):
        data = self.load()
        self._require_concept(data)
        page = self._page(data, page_id)
        data['page_approvals'][page_id] = {'reviewer':reviewer, 'user_statement':statement,
            'recorded_at':now(), 'page_sha256':digest(page), 'context_sha256':self._context(data),
            'concept_id':data['concept_approval']['concept_id'], 'scope':'page_design_only'}
        data['state'] = 'page_design_ready' if len(data['page_approvals']) == len(data['artifacts']['page_designs']['pages']) else 'awaiting_design_approval'
        return self._save(data, f'approve_page:{page_id}', reviewer, statement)

    @staticmethod
    def _page(data, page_id):
        for page in data['artifacts'].get('page_designs', {}).get('pages', []):
            if page['page_id'] == page_id:
                return page
        raise ValueError('Unknown page')

    def handoff(self, page_id, result_path):
        """Return an approved design, never launch a provider or promote mask review."""
        data = self.load()
        self._require_concept(data)
        page = self._page(data, page_id)
        approval = data['page_approvals'].get(page_id, {})
        if (approval.get('page_sha256') != digest(page) or
            approval.get('context_sha256') != self._context(data) or
            approval.get('concept_id') != data['concept_approval']['concept_id']):
            raise ValueError('This exact page design needs user approval')
        from product_studio.generation.compositor import load_foreground
        # Existing gate checks source RGB, hashes, instance and named mask review.
        mode = 'strict' if page['fidelity_level'] == 'strict_product' else 'preview'
        _, result, _ = load_foreground(Path(result_path), mode=mode,
                                      expected_instance=data['binding']['instance_id'])
        # Result metadata, not directory names, binds the selected asset.
        for key, expected in data['binding'].items():
            if key in ('source_id','source_sha256','instance_id','roi','mask_version','mask_sha256','rgba_sha256') and result['binding'].get(key) != expected:
                raise ValueError(f'Asset binding changed: {key}')
        prompt = '\n'.join(f'{label}: {json.dumps(value, ensure_ascii=False)}' for label, value in (
            ('Background only, no product', page['background_description']),
            ('Product center / reserved scale', [page['product_position'],page['product_scale']]),
            ('Composition / negative space / text reservation', page['composition']),
            ('Camera',page['camera_angle']), ('Lighting',page['lighting_design']),
            ('Focal point',page['focal_point']), ('Palette',page['color_palette']),
            ('Conflicts forbidden', 'No text, logos, extra products, contact floor or product shadows; do not paint the reserved product.')))
        return {'status':'approved_design_handoff_only', 'provider_submitted':False,
            'page_id':page_id, 'page_sha256':digest(page), 'binding':data['binding'],
            'background_prompt':prompt, 'page_design':deepcopy(page),
            'consumer_copy':deepcopy(page['consumer_copy']), 'final_asset_review_status':'pending'}
