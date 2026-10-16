"""Explicit runtime configuration and packaged resources, independent of a checkout."""
import json
import os
from importlib.resources import files
from pathlib import Path


def platform_preset(root, name):
    if name not in {'generic', 'amazon', 'ebay', 'social'}:
        raise ValueError('Unknown platform')
    configured = Path(root)/'configs/platform_presets'/f'{name}.json'
    # Legacy caller explicitly supplies its root; installed callers use wheel data.
    text = configured.read_text(encoding='utf-8') if configured.is_file() else files('product_studio.resources').joinpath('platform_presets',name+'.json').read_text(encoding='utf-8')
    return json.loads(text)


def available_font(language, bold=False):
    from PIL import ImageFont
    candidates = (['C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc'] if language=='zh' else [])
    candidates += ['C:/Windows/Fonts/arialbd.ttf' if bold else 'C:/Windows/Fonts/arial.ttf',
                   '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for name in candidates:
        if Path(name).is_file():
            if language=='zh' and 'msyh' not in name.lower():
                continue  # Do not silently render missing Chinese glyphs as boxes.
            return str(Path(name).resolve())
    raise ValueError('Configure style_preference.font_regular/font_bold with licensed local '+language+' fonts')


def provider_config(config_dir, output):
    from product_studio.providers.comfyui import save_json
    folder=Path(output)/'runtime_config';folder.mkdir(exist_ok=True)
    explicit=Path(config_dir)/'comfyui.json' if config_dir else None
    if explicit and explicit.exists():
        config=json.loads(explicit.read_text(encoding='utf-8'))
        config['workflow_path']=str((explicit.parent/config['workflow_path']).resolve())
    else:
        config=json.loads(files('product_studio.resources').joinpath('comfyui_template.json').read_text(encoding='utf-8'))
        workflow=folder/'qwen_image21_api.json'
        workflow.write_bytes(files('product_studio.resources').joinpath('qwen_image21_api.json').read_bytes())
        config['workflow_path']=str(workflow.resolve())
    config['base_url']=os.environ.get('COMFYUI_BASE_URL') or config.get('base_url')
    if not config['base_url']:
        raise ValueError('AI backgrounds require COMFYUI_BASE_URL or an explicit --config-dir/comfyui.json; no development-server fallback')
    destination=folder/'comfyui.json';save_json(destination,config)
    return destination.resolve()
