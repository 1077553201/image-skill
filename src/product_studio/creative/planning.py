import json
from pathlib import Path

from product_studio.core.asset_binding import file_sha256
from product_studio.core.schemas import Evidence, EvidenceStatus
from product_studio.generation.compositor import load_foreground
from product_studio.references.analysis import validate_analysis


def validate_facts(facts, binding):
    for key in ('instance_id','source_id','source_sha256','mask_version'):
        if facts['binding'][key] != binding[key]:
            raise ValueError('Product claims bound to another instance/version')
    for name, raw in facts['facts'].items():
        evidence = Evidence(**{**raw, 'status': EvidenceStatus(raw['status']), 'sources': tuple(raw.get('sources', []))})
        if evidence.status not in {EvidenceStatus.OBSERVED, EvidenceStatus.HUMAN_VERIFIED, EvidenceStatus.UNKNOWN}:
            raise ValueError('Estimated/conceptual claims cannot enter factual copy')
        if evidence.sources and set(evidence.sources) != {binding['source_id']}:
            raise ValueError('Fact belongs to a different source')
        if evidence.status != EvidenceStatus.UNKNOWN and not facts['provenance'].get(name):
            raise ValueError('Fact needs a provenance record')
    return facts


def create_plan(config, facts, analysis, catalog, root):
    validate_analysis(catalog, analysis)
    _, result, gate = load_foreground(root/config['source_result'], mode=config['mode'], expected_instance=config['instance_id'])
    validate_facts(facts, result['binding'])
    shots = config['shots']
    ids = [s['shot_id'] for s in shots]
    if not 1 <= len(shots) <= 32 or len(set(ids)) != len(shots):
        raise ValueError('Creative plan requires 1..32 uniquely identified shots')
    for shot in shots:
        if not shot.get('brief') or not shot.get('layers') or not shot.get('copy') and shot['role'] != 'white_hero':
            raise ValueError('Incomplete creative brief')
        for claim in shot.get('fact_ids', []):
            if claim not in facts['facts'] or facts['facts'][claim]['status'] == 'unknown':
                raise ValueError('Missing factual evidence for shot claim')
        for node in shot.get('text', []):
            for claim in node.get('fact_ids', []):
                if claim not in shot.get('fact_ids', []):
                    raise ValueError('Text claim not declared in shot evidence')
    return {**config, 'schema_version': 'creative_plan.4a.1', 'source_binding': result['binding'], 'review_gate': gate,
            'analysis_provider': analysis['provider'], 'reference_catalog_sha256': file_sha256(root/config['reference_catalog']),
            'facts_sha256': file_sha256(root/config['facts_path']), 'analysis_sha256': file_sha256(root/config['analysis_path']),
            'asset_human_review_status': 'pending', 'new_view_generated': False,
            'reference_pixels_allowed_as_layers': False}


def platform_check(preset, shot, *, occupancy):
    failures = []
    if preset['id'] == 'ebay' and (shot.get('text') or shot['role'] != 'white_hero' or shot.get('background_id')):
        failures.append('eBay listing photos disallow added text/artwork/marketing material')
    if shot['role'] == 'white_hero':
        if shot.get('text') or shot.get('background_id'):
            failures.append('White main-image mode requires unadorned product on white')
        if occupancy < preset.get('main_min_longest_axis_fill', 0):
            failures.append('Main image product fill below configured target')
    return {'preset': preset['id'], 'technical_failures': failures,
            'category_and_site_review_required': True, 'platform_approved': False,
            'use': 'main_image_candidate' if shot['role'] == 'white_hero' else 'marketing_asset_not_main_image',
            'policy_sources': preset.get('sources', [])}
