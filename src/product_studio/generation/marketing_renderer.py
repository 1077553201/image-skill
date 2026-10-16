"""Deterministic graphics/type over the existing, audited compositor.

No product-specific geometry rules. All layouts, callouts, facts and crops are explicit
Agent-authored configuration. Competitor assets are never accepted as render layers.
"""
import json
from pathlib import Path
import re
import shutil

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

from product_studio.core.asset_binding import file_sha256
from product_studio.creative.planning import platform_check
from product_studio.generation.compositor import load_foreground, compose_asset, composite_arrays
from product_studio.providers.comfyui import save_json


def _rgb(color):
    return tuple(bytes.fromhex(color.lstrip('#')))


def _luminance(rgb):
    rgb = np.asarray(rgb, dtype=np.float32)/255
    linear = np.where(rgb <= .04045, rgb/12.92, ((rgb+.055)/1.055)**2.4)
    return linear @ np.array([.2126,.7152,.0722])


def validate_copy(node, style, facts):
    from product_studio.creative.content_contract import validate_consumer_text
    validate_consumer_text(node['text'],style.get('production_disclosure'))
    words = re.findall(r'[A-Za-z]+', node['text'])
    vocabulary = {v.lower() for v in style['copy_vocabulary']}
    unknown = sorted({w for w in words if w.lower() not in vocabulary})
    if unknown:
        raise ValueError('Copy outside Agent-reviewed vocabulary: '+', '.join(unknown))
    forbidden = {w.lower() for w in style.get('excluded_copy_tokens', [])}
    if forbidden & {w.lower() for w in words}:
        raise ValueError('Competitor/prohibited unsupported copy')
    # Numeric quantities must agree with their own unit-labelled source fact.
    for number, unit in re.findall(r'(\d+(?:\.\d+)?)\s*(cm|mm|kg|g)\b', node['text']):
        valid = any(key.endswith('_'+unit) and facts['facts'][key]['value'] == float(number)
                    and facts['facts'][key]['status'] in {'observed','human_verified'} for key in node.get('fact_ids', []))
        if not valid:
            raise ValueError('Quantity text has no matching fact/unit')
    return {'controlled_copy_check':'passed', 'general_dictionary_spellcheck':False, 'numeric_claims_source_checked':True}


def draw_typography(canvas, nodes, style, facts, product_alpha=None):
    reports = []
    palette = style['palette']
    for node in nodes:
        copy_check = validate_copy(node, style, facts)
        # Pillow disallows top/bottom anchors on multiline; ascender anchor is supported.
        anchor = 'la' if '\n' in node['text'] else 'lt'
        font_path = style['font_bold'] if node.get('bold') else style['font_regular']
        size = node['size']
        while True:
            font = ImageFont.truetype(font_path, size)
            draw = ImageDraw.Draw(canvas)
            rendered_text=node['text']
            if node.get('prefer_explicit_lines') and size>16 and any(font.getlength(line)>node['max_width'] for line in rendered_text.split('\n')):
                size-=1
                continue
            if node.get('auto_wrap'):
                lines=[]
                for paragraph in rendered_text.split('\n'):
                    tokens=paragraph.split(' ') if ' ' in paragraph else list(paragraph)
                    joiner=' ' if ' ' in paragraph else ''
                    line=''
                    for token in tokens:
                        proposed=(line+joiner+token) if line else token
                        if line and font.getlength(proposed)>node['max_width']:
                            lines.append(line);line=token
                        else:line=proposed
                    lines.append(line)
                rendered_text='\n'.join(lines)
                anchor='la' if '\n' in rendered_text else 'lt'
            bbox = draw.multiline_textbbox((node['x'],node['y']), rendered_text, font=font, spacing=9, anchor=anchor)
            fits=bbox[2]-bbox[0]<=node.get('max_width',canvas.width) and bbox[3]-bbox[1]<=node.get('max_height',canvas.height)
            if fits or size <= 16:
                break
            size -= 1
        if not fits:raise ValueError('Text cannot fit without truncation: '+node['text'])
        margin = style['safe_margin_px']
        safe = bbox[0] >= margin and bbox[1] >= margin and bbox[2] <= canvas.width-margin and bbox[3] <= canvas.height-margin
        if not safe:
            raise ValueError('Text exceeds safe area: '+node['text'])
        glyph = Image.new('L', canvas.size)
        ImageDraw.Draw(glyph).multiline_text((node['x'],node['y']), rendered_text, font=font, spacing=9, anchor=anchor, fill=255)
        mask = np.asarray(glyph) > 220
        if not np.any(mask):
            raise ValueError('Text has no visible glyphs')
        if product_alpha is not None and np.any((np.asarray(glyph)>0) & (product_alpha>0)):
            raise ValueError('Text would obscure real product pixels: '+node['text'])
        ink = _rgb(palette.get(node['color'], node['color']))
        luminance = _luminance(np.asarray(canvas)[mask])
        text_lum = float(_luminance(ink))
        ratios = (np.maximum(luminance,text_lum)+.05)/(np.minimum(luminance,text_lum)+.05)
        minimum = float(ratios.min())
        required_contrast = 3.0 if size>=24 or (node.get('bold') and size>=19) else 4.5
        if minimum < required_contrast:
            raise ValueError('Text contrast below configured size-dependent minimum: '+node['text']+': '+str(minimum))
        ImageDraw.Draw(canvas).multiline_text((node['x'],node['y']), rendered_text, font=font, spacing=9, anchor=anchor, fill=ink)
        reports.append({**node, 'rendered_text':rendered_text,'truncated':False, 'actual_size':size, 'bbox':list(bbox), 'inside_safe_area':True,
                        'minimum_glyph_contrast':minimum, 'required_contrast':required_contrast,
                        'font_sha256':file_sha256(font_path), **copy_check})
    return reports


def photo_detail(rgba, bbox, size):
    x,y,w,h = bbox
    if min(w,h)<=0 or min(x,y)<0 or x+w>rgba.shape[1] or y+h>rgba.shape[0]:
        raise ValueError('Detail crop outside original image')
    crop = Image.fromarray(rgba[y:y+h,x:x+w])
    scale = min(size[0]/w, size[1]/h, 1.6)
    scaled = crop.convert('RGBa').resize((round(w*scale),round(h*scale)), Image.Resampling.LANCZOS).convert('RGBA')
    return scaled, {'source_bbox_xywh':bbox, 'source_size_px':[w,h], 'render_size_px':list(scaled.size),
                    'interpolation_scale':scale, 'real_detail_not_AI':True, 'resolution_limited':scale>1,
                    'new_texture_or_hidden_structure_generated':False}


def _background(root, plan, shot, out, records, rgba):
    palette = plan['style']['palette']
    ref_catalog = json.loads((root/plan['reference_catalog']).read_text(encoding='utf-8'))
    ref_hashes = {x['sha256'] for x in ref_catalog['assets']}
    if shot.get('background_id'):
        record = next(x for x in records if x['background_id']==shot['background_id'])
        execution = record['execution']
        if record['status']!='succeeded' or execution.get('status')!='succeeded' or not execution.get('prompt_id'):
            raise ValueError('Background has not actually succeeded')
        path = Path(record['path'])
        if file_sha256(path)!=execution['background_sha256'] or file_sha256(path) in ref_hashes:
            raise ValueError('Invalid or competitor-derived background')
        if (root/'data/references').resolve() in path.resolve().parents:
            raise ValueError('Reference pixels cannot be compositing material')
        with Image.open(path) as im:
            canvas = im.convert('RGB')
        provenance = dict(execution)
        if list(canvas.size)!=shot['size_px']:
            if shot.get('background_fit')!='cover':raise ValueError('Background size mismatch, no silent stretching')
            original_size=list(canvas.size)
            canvas=ImageOps.fit(canvas,tuple(shot['size_px']),method=Image.Resampling.LANCZOS)
            provenance['background_size_fit']={'source_size_px':original_size,'output_size_px':shot['size_px'],
                'method':'explicit uniform cover and crop; background only'}
        if shot.get('background_crop_xywh'):
            x,y,w,h=shot['background_crop_xywh']
            if min(x,y)<0 or min(w,h)<=0 or x+w>canvas.width or y+h>canvas.height:
                raise ValueError('Background crop outside generated image')
            canvas=ImageOps.fit(canvas.crop((x,y,x+w,y+h)),tuple(shot['size_px']),method=Image.Resampling.LANCZOS)
            provenance['background_derivation']={'source_background_sha256':execution['background_sha256'],
                'crop_xywh':shot['background_crop_xywh'],'output_size_px':shot['size_px'],
                'method':'uniform aspect-preserving fit after explicit background-only crop',
                'reason':'Remove horizontal light band that might imply a physical floor; product pixels untouched'}
    else:
        canvas = Image.new('RGB', shot['size_px'], palette[shot['background_color']])
        provenance = {'provider':'python_solid_color','status':'succeeded','color':palette[shot['background_color']],
                      'no_AI_generation_claimed':True,'human_review_status':'pending'}
    _,alpha,_,transform = composite_arrays(rgba,np.asarray(canvas),scale=shot['scale'],center_normalized=shot['center'])
    matrix = np.asarray(transform['matrix_source_to_output'])
    draw = ImageDraw.Draw(canvas)
    for panel in shot.get('panels',[]):
        x,y,w,h=panel['box']
        draw.rounded_rectangle((x,y,x+w,y+h),radius=panel.get('radius',0),fill=palette[panel['color']])
    for rule in shot.get('rules', []):
        draw.line(rule['xy'], fill=palette[rule['color']], width=rule['width'])
    for callout in shot.get('callouts', []):
        point = matrix @ np.array([*callout['source_point'],1])
        draw.line([tuple(point),tuple(callout['via']),tuple(callout['end'])], fill=palette['muted'], width=2)
        draw.ellipse((point[0]-4,point[1]-4,point[0]+4,point[1]+4),fill=palette['ink'])
    if shot.get('dimension_line'):
        y=shot['dimension_line']['y'];x1,_,x2,_=transform['output_visible_extent_xyxy']
        draw.line((x1,y,x2,y),fill=palette['muted'],width=2)
        for x in (x1,x2):
            draw.line((x,y-8,x,y+8),fill=palette['muted'],width=2)
    folder = out/'layout_backgrounds'
    folder.mkdir(exist_ok=True)
    path = folder/(shot['shot_id']+'.png')
    if path.exists():
        # Same plan may resume after a partially completed render; compare pixels first.
        with Image.open(path) as previous:
            if not np.array_equal(np.asarray(previous),np.asarray(canvas)):
                raise ValueError('Existing layout background changed')
    else:
        canvas.save(path)
    return path, {**provenance, 'original_generated_background':record if shot.get('background_id') else None,
                  'background_sha256':file_sha256(path),'layout_guides_added_by_python':True}


def render_set(root, plan, out, records):
    root, out = Path(root), Path(out)
    palette = plan['style']['palette']
    rgba, segmentation, gate = load_foreground(root/plan['source_result'], mode=plan['mode'], expected_instance=plan['instance_id'])
    if segmentation['binding'] != plan['source_binding']:
        raise ValueError('Foreground source/version changed since planning')
    for path_key, hash_key in [('facts_path','facts_sha256'),('analysis_path','analysis_sha256'),('reference_catalog','reference_catalog_sha256')]:
        if file_sha256(root/plan[path_key]) != plan[hash_key]:
            raise ValueError('Evidence or analysis changed after plan approval')
    facts = json.loads((root/plan['facts_path']).read_text(encoding='utf-8'))
    plan_hash = file_sha256(out/'creative_plan.json')
    manifests=[]
    for shot in plan['shots']:
        folder = out/shot['shot_id'];manifest_path=folder/'marketing_manifest.json'
        if manifest_path.exists():
            old=json.loads(manifest_path.read_text(encoding='utf-8'))
            if old['plan_sha256']!=plan_hash or file_sha256(folder/'final.png')!=old['output_sha256']:
                raise ValueError('Prior creative output changed; use a new version')
            manifests.append(old)
            continue
        bg, provenance = _background(root,plan,shot,out,records,rgba)
        config={'mode':plan['mode'],'instance_id':plan['instance_id'],'output_size_px':shot['size_px'],
                'scale':shot['scale'],'center_normalized':shot['center'],'shadow':{'mode':'none'}}
        compose_dir=folder/'composite'
        if not (compose_dir/'composite_manifest.json').exists():
            compose = compose_asset(root/plan['source_result'],bg,compose_dir,config,provenance)
        else:
            compose=json.loads((compose_dir/'composite_manifest.json').read_text(encoding='utf-8'))
            if compose['compose_config']!=config or compose['background']['background_sha256']!=file_sha256(bg):
                raise ValueError('Interrupted composite differs from current plan')
        with Image.open(compose_dir/'final.png') as im:canvas=im.convert('RGB')
        with Image.open(compose_dir/'transformed_alpha.png') as im:alpha=np.asarray(im).copy()
        detail_records=[]
        for detail in shot.get('details', []):
            x,y,w,h=detail['box']
            if np.any(alpha[y:y+h,x:x+w]):
                raise ValueError('Detail inset overlaps main product')
            tile, detail_record=photo_detail(rgba,detail['source_bbox'],[w,h])
            card=Image.new('RGB',(w,h),plan['style']['palette']['navy'])
            card.paste(tile,((w-tile.width)//2,(h-tile.height)//2),tile.getchannel('A'))
            canvas.paste(card,(x,y))
            detail_records.append({**detail_record,'box':detail['box'],'label':detail['label'],
                                   'source_binding':segmentation['binding']})
        if plan.get('schema_version')=='campaign_plan.4c.1':
            nodes=shot['consumer_copy']
        else:
            nodes=shot.get('consumer_copy',shot.get('text',[]))  # Historical plan adapter, still consumer-linted.
        texts = draw_typography(canvas,nodes,plan['style'],facts,alpha)
        palette = plan['style']['palette']
        # Exact reproduction test after type and crop layers; main-product pixels untouched.
        original = np.asarray(Image.open(compose_dir/'final.png'))
        protected = alpha>0
        preserved = bool(np.array_equal(np.asarray(canvas)[protected],original[protected]))
        if not preserved:
            raise ValueError('Marketing layers changed protected product pixels')
        canvas.save(folder/'final.png')
        extent=compose['transform']['output_visible_extent_xyxy']
        occupancy=max((extent[2]-extent[0]+1)/canvas.width,(extent[3]-extent[1]+1)/canvas.height)
        from product_studio.configuration import platform_preset
        platform=platform_preset(root,shot['target_platform'])
        manifest={'schema_version':'marketing.4a.1','shot_id':shot['shot_id'],'role':shot['role'],
                  'generation_route':plan.get('generation_route'),
                  'consumer_copy_channel':plan.get('task_intent_contract',{}).get('render_channel','legacy_consumer_adapter'),
                  'plan_sha256':plan_hash,'brief':shot,'source_binding':segmentation['binding'],'review_gate':gate,
                  'source_foreground_unchanged':True,'final_main_product_pixels_equal_composite':preserved,
                  'composite_manifest':str((compose_dir/'composite_manifest.json').resolve()),
                  'text_checks':texts,'detail_crops':detail_records,'background':provenance,
                  'reference_pixels_used':False,'source_image_sent_to_generation':False,
                  'platform_check':platform_check(platform,shot,occupancy=occupancy),
                  'product_longest_axis_fill':occupancy,'new_view_generated':False,
                  'visual_review_status':'pending','asset_human_review_status':'pending',
                  'output_sha256':file_sha256(folder/'final.png'),'output_path':str((folder/'final.png').resolve()),
                  'warnings':['Same source front view in every asset; not new photography angles',
                              'Larger display sizes use interpolation, not extra real detail',
                              'Claims limited to source-bound facts; supplied values are not independent measurements',
                              'No automated brand/logo detector or general semantic proof is claimed']}
        save_json(manifest_path,manifest)
        manifests.append(manifest)
        print(shot['shot_id']+' rendered; final asset pending',flush=True)
    thumbnails=[]
    for manifest in manifests:
        with Image.open(manifest['output_path']) as im:
            thumbnails.append(ImageOps.contain(im.convert('RGB'),(392,315)))
    sheet=Image.new('RGB',(1600,370*((len(manifests)+3)//4)),'#e7ebee');draw=ImageDraw.Draw(sheet)
    titlefont=ImageFont.truetype(plan['style']['font_bold'],19)
    for i,(thumb,manifest) in enumerate(zip(thumbnails,manifests)):
        x=(i%4)*400;y=(i//4)*370
        sheet.paste(thumb,(x+(400-thumb.width)//2,y+8+(315-thumb.height)//2))
        draw.text((x+12,y+330),manifest['shot_id'],fill='#17252b',font=titlefont)
    sheet.save(out/'creative_set_contact_sheet.png')
    means=[]
    for m in manifests:
        with Image.open(m['output_path']) as im:means.append(np.asarray(im.resize((128,128))).astype(float))
    differences=[{'a':manifests[i]['shot_id'],'b':manifests[j]['shot_id'],'mean_absolute_rgb_difference':float(np.abs(means[i]-means[j]).mean())} for i in range(len(means)) for j in range(i)]
    set_manifest={'schema_version':'creative_set.4a.1','instance_id':plan['instance_id'],'source_binding':segmentation['binding'],
                  'images':manifests,'pairwise_visual_differences':differences,'duplicate_metric_is_semantic_detector':False,
                  'asset_human_review_status':'pending','all_product_pixels_preserved':all(m['final_main_product_pixels_equal_composite'] for m in manifests)}
    save_json(out/'manifest.json',set_manifest)
    return set_manifest
