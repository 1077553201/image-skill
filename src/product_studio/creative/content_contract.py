"""Consumer text and production context use separate channels; no implicit disclosure."""
from copy import deepcopy
import re


INTERNAL_PATTERNS=(r'\b(?:pipeline|skill|agent|evidence)\b',r'\bmask(?:\s+review|\s+version)?\b',
    r'项目开发|工程验证|源像素保留|原图真实性审核|项目阶段|自动化测试|这是原始商品图片|仅展示原图',
    r'AI\s*生成流程|真实性审核|阶段\s*\d',
    r'original photograph|source photograph|source (?:image|pixels)|pixels in the source|non.contact editorial presentation')


def validate_consumer_text(text,authorization=None):
    if authorization and authorization.get('allow_production_disclosure') is True and authorization.get('user_statement'):
        return
    if any(re.search(p,text,re.I) for p in INTERNAL_PATTERNS):
        raise ValueError('Internal production language cannot enter consumer_copy without explicit user disclosure authorization')


def task_contract(request,analysis):
    intent=request.get('task_intent','product_marketing')
    if intent!='product_marketing':raise ValueError('Campaign generator handles product_marketing; development requests are not advertising jobs')
    out=deepcopy(analysis)
    consumer=deepcopy(analysis.get('consumer_copy',analysis.get('copy',{})))
    auth=request.get('production_disclosure')
    for copy in consumer.values():
        for key in ('headline','body'):validate_consumer_text(str(copy.get(key,'')),auth)
    for feature in out.get('features',[]):
        for key in ('title','description'):validate_consumer_text(str(feature.get(key,'')),auth)
    for detail in out.get('detail_regions',[]):validate_consumer_text(detail.get('label',''),auth)
    out['consumer_copy']=consumer
    out['copy']=consumer  # Legacy compiler input adapter; never populated from internal notes.
    out['internal_notes']=deepcopy(analysis.get('internal_notes',{}))
    out['task_intent_contract']={'intent':intent,'render_channel':'consumer_copy','production_disclosure':auth,
                               'internal_notes_rendered':False}
    return out
