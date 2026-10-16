"""小规模场景规划与可追溯背景缓存；复用现有ComfyUI Provider。"""
import io,json
from pathlib import Path
from urllib.parse import urlencode
import numpy as np

from PIL import Image

from product_studio.core.asset_binding import file_sha256
from product_studio.providers.comfyui import digest,save_json


def canonical(value):return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()


def load_configuration(product_set_path,presets_path):
    config=json.loads(Path(product_set_path).read_text(encoding='utf-8'))
    presets=json.loads(Path(presets_path).read_text(encoding='utf-8'))
    if config.get('schema_version')!='product_set.3b.1' or presets.get('schema_version')!='scene_presets.3b.1':raise ValueError('不支持的场景/图集配置版本')
    size=config['output_size_px'];count=config['candidates_per_lifestyle']
    if len(size)!=2 or any(type(v)!=int or v<64 or v%8 for v in size):raise ValueError('输出尺寸必须为8的倍数')
    if type(count)!=int or not 1<=count<=8:raise ValueError('每场景候选数必须为1..8')
    names=[a['instance_id'] for a in config['assets']]
    if not names or len(names)!=len(set(names)):raise ValueError('实例标识必须非空且唯一')
    for asset in config['assets']:
        if not asset['instance_id'] or asset['mode'] not in {'strict','preview'}:raise ValueError('无效实例/模式')
        preset=presets['presets'][asset['preset']]
        for key in ('goal','positive_prompt','negative_prompt','color_tendency','lighting_direction','composition','placement_region_normalized','allow_floor','allow_visible_horizon','allow_props','risk_rules'):
            if key not in preset:raise ValueError('场景预设缺失字段: '+key)
        if asset.get('visible_view') not in preset['compatible_views']:raise ValueError('当前视角不支持此预设，不能扭曲前景适配')
        if preset['allow_floor'] or preset['allow_visible_horizon'] or preset['allow_props']:raise ValueError('当前阶段仅支持无地面/道具的正面抽象预设')
        x,y,w,h=preset['placement_region_normalized']
        if min(x,y)<0 or min(w,h)<=0 or x+w>1 or y+h>1:raise ValueError('商品放置区域不合法')
    return config,presets['presets']


def make_plan(config,presets,provider,bindings):
    plan=[]
    for asset in config['assets']:
        binding=bindings[asset['instance_id']];preset=presets[asset['preset']]
        for i in range(config['candidates_per_lifestyle']):
            seed_material=[config.get('seed_base',0),binding['source_sha256'],asset['instance_id'],asset['preset'],i]
            seed=int(digest(canonical(seed_material))[:8],16)
            plan.append({'instance_id':asset['instance_id'],'candidate_id':chr(65+i),'preset':asset['preset'],
                         'mode':asset['mode'],'prompt':preset['positive_prompt'],'negative':preset['negative_prompt'],
                         'width':config['output_size_px'][0],'height':config['output_size_px'][1],'seed':seed,
                         'source_binding':binding,'visible_view':asset['visible_view'],'view_evidence':asset['view_evidence']})
    return plan


def compose_configuration(asset,preset,rgba,size):
    """尺寸变化时自动等比例适配放置区；scale仅为可选的原像素比例上限。"""
    ys,xs=np.where(rgba[:,:,3]>0)
    if not len(xs):raise ValueError('空前景不能规划构图')
    x,y,w,h=preset['placement_region_normalized'];width,height=size
    fit=min((w*width-12)/(xs.max()-xs.min()+1),(h*height-12)/(ys.max()-ys.min()+1))
    scale=min(float(asset.get('scale',1.0)),float(fit))
    if scale<=0:raise ValueError('放置区域不足')
    return {'instance_id':asset['instance_id'],'mode':asset['mode'],'output_size_px':size,'scale':scale,
            'center_normalized':preset['center_normalized'],'shadow':{'mode':'none'}}


class BackgroundCache:
    def __init__(self,provider,root):self.provider=provider;self.root=Path(root)

    def key(self,task):
        effective=self.provider.prepare(task['prompt'],task['negative'],task['width'],task['height'],task['seed'],'CACHE_KEY_ONLY')
        recipe={'base_url':self.provider.base,'workflow':effective,'template_sha256':self.provider.template_hash,
                'output_node':self.provider.config['output_node'],'instance_id':task['instance_id'],
                'source_id':task['source_binding']['source_id'],'source_sha256':task['source_binding']['source_sha256'],
                'mask_version':task['source_binding']['mask_version'],'mode':task['mode']}
        return digest(canonical(recipe))

    def get(self,task):
        key=self.key(task);directory=self.root/key
        request_path=directory/'request.json';attempt=directory/'attempt_001'
        if request_path.exists():
            request=json.loads(request_path.read_text(encoding='utf-8'))
            if request['task']!=task:raise ValueError('缓存任务与当前实例配置不一致')
            for filename,image_name in [('recovery.json','recovered_background.png'),('execution.json','background.png')]:
                record_path=attempt/filename
                if record_path.exists():
                    record=json.loads(record_path.read_text(encoding='utf-8'))
                    if record.get('status')=='succeeded':
                        image=attempt/image_name;self._validate_image(image.read_bytes(),task,record)
                        return image,record,{'cache_hit':True,'cache_key':key,'recovered':filename=='recovery.json'}
            return self._recover(task,attempt,key)
        directory.mkdir(parents=True,exist_ok=False)
        save_json(request_path,{'task':task,'cache_key':key,'schema_version':'background_cache.3b.1'})
        try:
            image,record=self.provider.generate(task['prompt'],task['negative'],width=task['width'],height=task['height'],seed=task['seed'],output_dir=attempt)
            self._validate_image(image.read_bytes(),task,record)
            return image,record,{'cache_hit':False,'cache_key':key,'recovered':False}
        except Exception as exc:
            save_json(directory/'failure.json',{'type':type(exc).__name__,'message':str(exc),'automatic_retry':False,'scope':'this candidate only'})
            raise

    @staticmethod
    def _validate_image(raw,task,record):
        if digest(raw)!=record.get('background_sha256'):raise ValueError('缓存背景哈希不符，拒绝静默重新生图')
        if record.get('seed')!=task['seed'] or record.get('prompt')!=task['prompt'] or record.get('negative_prompt')!=task['negative']:raise ValueError('缓存生成参数不符')
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            if im.format!='PNG' or im.size!=(task['width'],task['height']):raise ValueError('缓存图片格式/尺寸不符')

    def _recover(self,task,attempt,key):
        execution=attempt/'execution.json'
        if not execution.exists():raise RuntimeError('上次提交状态不明，禁止自动重发；请核对远程队列与历史')
        prior=json.loads(execution.read_text(encoding='utf-8'));pid=prior.get('prompt_id')
        if not pid:raise RuntimeError('失败记录没有prompt_id；保留失败，不自动重试')
        history=self.provider.request('/history/'+pid)
        if pid not in history:raise RuntimeError('原任务未完成/历史不可用；禁止重复提交，稍后再恢复 '+pid)
        item=history[pid]
        if item.get('status',{}).get('status_str')!='success' or not item.get('status',{}).get('completed'):raise RuntimeError('原任务没有成功，不自动重试 '+pid)
        images=item.get('outputs',{}).get(self.provider.config['output_node'],{}).get('images',[])
        if len(images)!=1 or images[0].get('type')!='output':raise RuntimeError('恢复任务没有有效单张输出')
        graph=json.loads((attempt/'submitted_workflow.json').read_text(encoding='utf-8'))
        if item['prompt'][1]!=pid or canonical(item['prompt'][2])!=canonical(graph):raise ValueError('恢复历史与原提交工作流不符')
        raw=self.provider.transport('/view?'+urlencode({k:images[0].get(k,'') for k in ('filename','subfolder','type')}),None)
        record={**prior,'status':'succeeded','background_sha256':digest(raw),'image':images[0],
                'resumed_from':str(execution),'recovery_did_not_resubmit':True}
        self._validate_image(raw,task,record)
        image=attempt/'recovered_background.png';image.write_bytes(raw)
        save_json(attempt/'recovery_history.json',item);save_json(attempt/'recovery.json',record)
        return image,record,{'cache_hit':True,'cache_key':key,'recovered':True}
