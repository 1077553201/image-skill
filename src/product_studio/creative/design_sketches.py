"""Low resolution review sketches, not production rendering or AI generation."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from product_studio.configuration import available_font
from .design_workflow import validate_page


def render_sketch(page, rgba_path, output, font_path=None, size=640):
    validate_page(page)
    font_path = font_path or available_font('zh')
    canvas = Image.new('RGB', (size, size), page['color_palette'][0])
    draw = ImageDraw.Draw(canvas)
    with Image.open(rgba_path) as source:
        rgba = source.convert('RGBA')
    def rect(box):
        x,y,w,h = box
        return (round(x*size),round(y*size),round((x+w)*size),round((y+h)*size))
    for layer in sorted(page['layer_structure'], key=lambda x:x['z']):
        kind = layer['kind']
        if kind == 'background':
            continue  # Flat color is deliberate; AI backdrop has not been made.
        if kind == 'graphic':
            draw.rectangle(rect(layer['rect']), fill=layer['color'])
        elif kind in ('source_foreground','source_crop'):
            image = rgba.copy()
            if kind == 'source_crop':
                x,y,w,h = layer['crop_xywh']
                image = image.crop((x,y,x+w,y+h))
            else:
                image = image.crop(image.getbbox())
            x1,y1,x2,y2 = rect(layer['rect'])
            image.thumbnail((x2-x1,y2-y1),Image.Resampling.LANCZOS)
            canvas.paste(image,(x1+(x2-x1-image.width)//2,y1+(y2-y1-image.height)//2),image)
        elif kind == 'type':
            text = page['consumer_copy'].get(layer['copy_key'],'')
            font = ImageFont.truetype(font_path,round(layer['size']*size))
            x,y,_,_ = rect(layer['rect'])
            draw.multiline_text((x,y),text,font=font,fill=layer['color'],spacing=round(.014*size))
    # A separate review band never becomes consumer copy or a production layer.
    result = Image.new('RGB',(size,size+52),'#17212a')
    result.paste(canvas,(0,0))
    label = f"{page['page_id']} · 布局草图 / 非成品 · 背景尚未生成"
    ImageDraw.Draw(result).text((14,size+15),label,font=ImageFont.truetype(font_path,17),fill='white')
    target = Path(output); target.parent.mkdir(parents=True,exist_ok=True);result.save(target)
    return target


def contact_sheet(paths, output):
    paths = list(paths)
    with Image.open(paths[0]) as first:
        w,h = first.size
    sheet=Image.new('RGB',(w*3,h*2),'#f3f1ec')
    for index,path in enumerate(paths):
        with Image.open(path) as im:
            sheet.paste(im,((index%3)*w,(index//3)*h))
    sheet.save(output)
