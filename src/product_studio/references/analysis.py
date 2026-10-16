"""Validate image-bound analysis supplied by an image-capable Agent, not a fake API."""
import json
from pathlib import Path
from product_studio.core.asset_binding import file_sha256

DIMENSIONS = ('art_direction', 'palette', 'background', 'lighting', 'composition',
              'product_placement', 'copy_hierarchy', 'typography', 'negative_space',
              'image_text_layout', 'material_detail', 'benefit_expression', 'set_cohesion', 'sales_role')


def validate_analysis(catalog, analysis):
    if analysis.get('provider') != 'image_capable_agent' or analysis.get('separate_vlm_api_called') is not False:
        raise ValueError('This handoff requires honestly declared Agent image analysis')
    assets = {x['asset_id']: x for x in catalog['assets']}
    records = analysis.get('images', [])
    if len(records) != len(assets) or {x['asset_id'] for x in records} != set(assets):
        raise ValueError('Every collected image needs one visual analysis')
    for item in records:
        asset = assets[item['asset_id']]
        if item.get('sha256') != asset['sha256'] or file_sha256(asset['path']) != asset['sha256']:
            raise ValueError('Reference analysis image hash mismatch')
        if item.get('image_read_tool') != 'view_image' or set(item.get('dimensions', {})) != set(DIMENSIONS):
            raise ValueError('Missing actual image-read declaration or analysis dimensions')
        if any(not isinstance(v, str) or not v.strip() for v in item['dimensions'].values()):
            raise ValueError('Empty visual observation')
    if set(analysis.get('summary', {})) != set(DIMENSIONS):
        raise ValueError('Missing set-wide analysis')
    if not analysis.get('transferable') or not analysis.get('excluded'):
        raise ValueError('Need transferable methods and explicit exclusions')
    return analysis


def analysis_markdown(analysis):
    lines = ['# 参考图视觉分析', '',
             '按用户最新要求，由当前具备图像能力的 Agent 通过 view_image 逐张读取真实文件。未调用独立 VLM API；该判断不是确定性几何测量，也不是用户审核。', '']
    for record in analysis['images']:
        lines += [f"## {record['asset_id']}：{record['role']}", '']
        lines += [f'- {key}: {value}' for key, value in record['dimensions'].items()]
        lines += ['']
    lines += ['## 整套设计语言', ''] + [f'- {k}: {v}' for k,v in analysis['summary'].items()]
    lines += ['', '## 可迁移方法', ''] + ['- '+x for x in analysis['transferable']]
    lines += ['', '## 禁止复用与不适用项', ''] + ['- '+x for x in analysis['excluded']]
    lines += ['', '## 获取限制', '', f"本次实际分析 {len(analysis['images'])} 张图片。来源与获取缺失以对应 catalog.json 为准；不可把本地原创参考当作竞品实站获取记录。"]
    return '\n'.join(lines)+'\n'
