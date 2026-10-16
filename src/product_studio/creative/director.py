"""Campaign-directed composition families. Product category never selects a template."""
import numpy as np


FAMILIES=('full_frame','asymmetric_editorial','typographic_poster','minimal_negative_space',
          'magazine_cover','macro_story','technical_grid','wide_atmosphere')


def foreground_bounds(rgba):
    yy,xx=np.where(rgba[:,:,3]>0)
    if not len(xx):raise ValueError('Empty foreground')
    return [int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)]


def placement(rgba,box,size,max_scale=1.4):
    bounds=foreground_bounds(rgba);x,y,w,h=box
    if min(w,h)<=16:raise ValueError('Subject safe box too small')
    scale=min((w-12)/(bounds[2]-bounds[0]),(h-12)/(bounds[3]-bounds[1]),max_scale)
    return float(scale),[(x+w/2)/size[0],(y+h/2)/size[1]]


def compile_directed_layout(intent,index,request,analysis,facts,rgba,style,background_ids):
    direction={**analysis.get('creative_direction',{}),**request.get('creative_direction',{})}
    choices=direction.get('intent_layouts',{})
    defaults={'white_hero':'full_frame','studio_photo':'full_frame','brand_signature':'magazine_cover',
              'editorial_campaign':'typographic_poster','feature_infographic':'asymmetric_editorial',
              'structure_explainer':'technical_grid','specifications':'technical_grid',
              'material_detail':'macro_story','lifestyle_scene':'minimal_negative_space','wide_banner':'wide_atmosphere'}
    selected=choices.get(intent,{});selected={'family':selected} if isinstance(selected,str) else selected
    family=selected.get('family',defaults.get(intent,'asymmetric_editorial'))
    if family not in FAMILIES:raise ValueError('Unsupported layout family: '+str(family))
    if family=='macro_story' and not analysis.get('detail_regions'):raise ValueError('Macro story requires an actual source crop')
    size=request['output_sizes'].get(intent,request['output_sizes']['default']);width,height=size
    box=lambda x,y,w,h:[round(x*width),round(y*height),round(w*width),round(h*height)]
    copy=analysis.get('consumer_copy',analysis.get('copy',{})).get(intent,{})
    headline=copy.get('headline') or analysis['display_name'];body=copy.get('body','');claims=copy.get('fact_ids',[])
    text=[];details=[];rules=[]
    color='white' if style.get('dark_background') else 'ink'
    background='environment' if intent=='lifestyle_scene' else 'studio' if intent in ('studio_photo','brand_signature','editorial_campaign','wide_banner') else None
    if background not in background_ids:background=None
    background_color='navy' if style.get('dark_background') else 'paper'
    def node(value,region,font=32,bold=False,ids=claims):
        if not value:return
        x,y,w,h=region
        text.append({'text':str(value),'x':x,'y':y,'size':round(font*min(size)/1024),'bold':bold,'color':color,
                     'fact_ids':list(ids),'max_width':w,'max_height':h,'auto_wrap':True,
                     'prefer_explicit_lines':'\n' in str(value),'channel':'consumer_copy'})
    if intent=='white_hero':
        family='full_frame';subject=box(.06,.06,.88,.88);background=None;background_color='white'
    elif family=='full_frame':
        subject=box(.10,.07,.80,.70)
        node(headline,box(.07,.80,.86,.09),54,True)
        node(body,box(.07,.915,.86,.035),20)
    elif family=='asymmetric_editorial':
        subject=box(.07,.08,.61,.62)
        node(headline,box(.42,.74,.51,.12),47,True)
        node(body,box(.07,.83,.29,.10),23)
        rules=[{'xy':[round(.42*width),round(.71*height),round(.93*width),round(.71*height)],'color':'line','width':2}]
    elif family=='typographic_poster':
        node(headline,box(.065,.065,.87,.27),86,True)
        node(body,box(.065,.68,.31,.23),27)
        subject=box(.43,.36,.50,.57)
        rules=[{'xy':[round(.065*width),round(.41*height),round(.33*width),round(.41*height)],'color':'line','width':4}]
    elif family=='minimal_negative_space':
        node(headline,box(.08,.12,.77,.14),48,True)
        node(body,box(.08,.74,.30,.15),23)
        subject=box(.52,.39,.40,.49)
    elif family=='magazine_cover':
        node(headline,box(.065,.065,.87,.105),67,True)
        subject=box(.13,.23,.74,.58)
        node(body,box(.25,.87,.68,.07),25)
        rules=[{'xy':[round(.065*width),round(.86*height),round(.18*width),round(.86*height)],'color':'line','width':5}]
    elif family=='macro_story':
        node(headline,box(.07,.065,.86,.14),59,True)
        crop=analysis['detail_regions'][0]
        details=[{'source_bbox':crop['bbox'],'box':box(.07,.26,.60,.52),'label':crop['label']}]
        subject=box(.73,.62,.20,.25)
        node(crop['label'],box(.07,.81,.59,.07),29,True,crop.get('fact_ids',[]))
        node(body,box(.07,.91,.86,.035),20)
    elif family=='technical_grid':
        node(headline,box(.065,.065,.87,.13),52,True)
        subject=box(.52,.34,.41,.49)
        entries=[]
        if intent=='specifications':
            for key,fact in facts['facts'].items():
                if analysis.get('fact_kinds',{}).get(key)=='quantity' and fact['status']!='unknown':
                    unit=key.rsplit('_',1)[-1];entries.append({'title':str(fact['value'])+' '+unit,'description':key.rsplit('_',1)[0].replace('_',' '),'fact_ids':[key]})
        else:entries=analysis.get('features',[])[:3]
        for i,entry in enumerate(entries[:3]):
            y=.31+i*.19
            node(entry['title'],box(.065,y,.38,.07),33,True,entry['fact_ids'])
            node(entry.get('description',''),box(.065,y+.08,.38,.08),21,False,entry['fact_ids'])
        node(body,box(.065,.89,.87,.05),20)
    else:  # wide_atmosphere
        subject=box(.07,.14,.43,.71)
        node(headline,box(.59,.21,.34,.32),64,True)
        node(body,box(.59,.69,.34,.16),25)
    scale,center=placement(rgba,subject,size,max_scale=1.4 if intent=='white_hero' else 1.0)
    visible=foreground_bounds(rgba)
    shot={'shot_id':f'{index+1:02d}_{intent}','role':intent,'intent':intent,'size_px':size,'scale':scale,'center':center,
          'copy':headline,'brief':copy.get('brief') or 'Consumer product campaign',
          'fact_ids':sorted({k for n in text for k in n['fact_ids']}),'text':text,'consumer_copy':text,
          'details':details,'panels':[],'rules':rules,'background_id':background,'background_color':background_color,'background_fit':'cover',
          'target_platform':request['platform'],'audience':direction.get('target_buyer',analysis.get('audience','Prospective buyers')),
          'layout':{'template':family,'family':family,'subject_safe_box':subject,'visible_bbox':visible,'adaptive':True,
                    'selection_reason':selected.get('reason') or 'Purpose '+intent+' with campaign goal '+direction.get('campaign_goal','product awareness')},
          'creative_axes':{k:direction.get(k) for k in ('product_use','target_buyer','campaign_goal','reference_language','mood','photography_scene','information_density','sequence_rationale')},
          'layers':['independent_background','source_foreground','real_detail_crop_if_requested','consumer_copy'],
          'scene_level':1,'presentation':'non_contact_atmosphere' if background else 'foreground_composite',
          'authenticity_limits':['Same source view','No inferred contact or hidden geometry','Final asset pending user review']}
    shot['layout_signature']=layout_signature(shot)
    return shot


def layout_signature(shot):
    w,h=shot['size_px'];b=shot['layout'].get('visible_bbox',[0,0,0,0]);scale=shot['scale']
    nodes=shot.get('consumer_copy',shot.get('text',[]))
    return {'family':shot['layout'].get('family',shot['layout']['template']),'subject_center':shot['center'],
            'subject_box_fraction':[scale*(b[2]-b[0])/w,scale*(b[3]-b[1])/h],
            'subject_area_fraction':scale**2*(b[2]-b[0])*(b[3]-b[1])/(w*h),
            'title_position':[nodes[0]['x']/w,nodes[0]['y']/h] if nodes else None,
            'text_zones':[[n['x']/w,n['y']/h,n['max_width']/w,n['max_height']/h] for n in nodes],
            'background_type':'generated_'+shot['background_id'] if shot.get('background_id') else 'solid_'+shot['background_color'],
            'detail_windows':len(shot.get('details',[])),'panels':len(shot.get('panels',[]))}


def repetition_risks(shots):
    signatures=[layout_signature(s) for s in shots];risks=[]
    for i,a in enumerate(signatures):
        for j,b in enumerate(signatures[:i]):
            if shots[i]['role']==shots[j]['role']=='white_hero':continue
            distance=float(np.linalg.norm(np.array(a['subject_center'])-b['subject_center']))
            size_delta=float(np.linalg.norm(np.array(a['subject_box_fraction'])-b['subject_box_fraction']))
            if a['family']==b['family'] and distance<.08 and size_delta<.14:
                risks.append({'a':shots[j]['shot_id'],'b':shots[i]['shot_id'],'family':a['family'],
                              'center_distance':distance,'size_distance':size_delta,'status':'composition_repetition_risk'})
    return {'signatures':signatures,'risks':risks,'metric_is_aesthetic_approval':False}
