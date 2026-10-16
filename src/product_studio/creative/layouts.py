"""Declarative layout compiler: alpha bounds, output aspect and text boxes, never SKU geometry."""
import re
import numpy as np

from product_studio.creative.intents import TYPES
from product_studio.creative.director import foreground_bounds,placement,compile_directed_layout


def compile_layout(intent,index,request,analysis,facts,rgba,style,background_ids):
    explicit_legacy_panel=intent=='lifestyle_scene' and request.get('scene',{}).get('level')==2
    if request.get('creative_direction',{}).get('enabled') and not explicit_legacy_panel:
        return compile_directed_layout(intent,index,request,analysis,facts,rgba,style,background_ids)
    size=request['output_sizes'].get(intent,request['output_sizes']['default']);width,height=size
    m=round(min(size)*.06)
    box=lambda x,y,w,h:[round(x*width),round(y*height),round(w*width),round(h*height)]
    text=[];details=[];panels=[];rules=[]
    copy=analysis.get('copy',{}).get(intent,{})
    title=copy.get('headline') or analysis['display_name']
    body=copy.get('body','')
    claim_ids=list(copy.get('fact_ids',[]))
    layout=TYPES[intent].layout
    bounds=foreground_bounds(rgba);aspect=(bounds[2]-bounds[0])/(bounds[3]-bounds[1])
    def node(value,region,font=30,bold=False,color='ink',claims=()):
        x,y,w,h=region
        text.append({'text':str(value),'x':x,'y':y,'size':round(font*min(size)/1024),'bold':bold,
                     'color':color,'fact_ids':list(claims),'max_width':w,'max_height':h,'auto_wrap':True,
                     'prefer_explicit_lines':'\n' in str(value)})
    def title_node(color='ink'):
        node(title,box(.06,.06,.87,.16),58,True,color,claim_ids)
    if intent=='white_hero':
        subject=[m,m,width-2*m,height-2*m];text=[];background=None
    elif layout=='detail_panes':
        title_node();subject=box(.06,.30,.43,.52);background=None
        crops=analysis['detail_regions'][:2]
        for i,detail in enumerate(crops):
            target=box(.56,.29+i*.30,.37,.21 if len(crops)>1 else .43)
            details.append({'source_bbox':detail['bbox'],'box':target,'label':detail['label']})
            node(detail['label'],box(.56,.23+i*.30,.37,.05),22,True,claims=detail.get('fact_ids',[]))
        if body:node(body,box(.06,.90,.87,.045),20,claims=claim_ids)
    elif layout=='environment_panel':
        title_node();subject=box(.09,.28,.52,.58);background='environment'
        panels=[{'box':box(.035,.035,.93,.17),'color':'paper','radius':12},
                {'box':box(.06,.24,.58,.68),'color':'paper','radius':12}]
        if body:node(body,box(.09,.86,.52,.045),19,claims=claim_ids)
    elif intent in ('feature_infographic','structure_explainer','specifications'):
        title_node();subject=box(.06,.29,.50,.55);background=None
        entries=[]
        if intent=='specifications':
            for key,fact in facts['facts'].items():
                if analysis.get('fact_kinds',{}).get(key)=='quantity' and fact['status']!='unknown':
                    unit=key.rsplit('_',1)[-1] if '_' in key else ''
                    label=key.rsplit('_',1)[0].replace('_',' ').title()
                    entries.append({'title':f"{fact['value']} {unit}".strip(),'description':label,'fact_ids':[key]})
        else:
            entries=analysis.get('features',[])[:3]
            if intent=='structure_explainer':entries=[e for e in entries if any(analysis.get('fact_kinds',{}).get(k)=='structure' for k in e['fact_ids'])]
        for i,entry in enumerate(entries[:3]):
            y=.31+i*.19
            node(entry['title'],box(.63,y,.31,.09),31,True,claims=entry['fact_ids'])
            node(entry.get('description',''),box(.63,y+.095,.31,.075),21,False,'muted',entry['fact_ids']) if entry.get('description') else None
        if body:node(body,box(.06,.91,.87,.045),20,claims=claim_ids)
    elif layout=='centered' or aspect>1.6 and layout!='wide':
        title_node('white' if intent=='studio_photo' and style.get('dark_background') else 'ink')
        subject=box(.12,.26,.76,.60);background='studio' if intent=='studio_photo' else None
        if body:node(body,box(.06,.91,.87,.045),20,False,'white' if background and style.get('dark_background') else 'muted',claim_ids)
    else:
        dark=style.get('dark_background',False);color='white' if dark and 'studio' in background_ids else 'ink'
        node(title,box(.06,.14,.42,.35),67 if layout=='wide' else 60,True,color,claim_ids)
        if body:node(body,box(.06,.67,.40,.16),25,False,color,claim_ids)
        subject=box(.55,.16,.39,.73);background='studio'
    if background not in background_ids:background=None
    scale,center=placement(rgba,subject,size,max_scale=1.4 if intent=='white_hero' else 1.0)
    shot={'shot_id':f'{index+1:02d}_{intent}','role':intent,'intent':intent,'size_px':size,'scale':scale,'center':center,
          'copy':title,'brief':copy.get('brief') or TYPES[intent].applicability,'fact_ids':sorted(set(claim_ids+[k for n in text for k in n['fact_ids']])),
          'text':text,'consumer_copy':text,'details':details,'panels':panels,'rules':rules,'background_id':background,
          'background_color':'white' if intent=='white_hero' else 'paper','background_fit':'cover',
          'target_platform':request['platform'],'audience':analysis.get('audience','Prospective product buyers'),
          'layout':{'template':layout,'subject_safe_box':subject,'visible_bbox':bounds,'source_aspect':aspect,'adaptive':True},
          'layers':['independent_background','editorial_panel_if_environment','source_foreground','real_detail_crops','deterministic_type'],
          'authenticity_limits':['Original visible view only','No contact/occlusion editing','No hidden geometry synthesis'],
          'scene_level':2 if intent=='lifestyle_scene' else 1,'presentation':'editorial_panel' if intent=='lifestyle_scene' else 'foreground_composite'}
    return shot
