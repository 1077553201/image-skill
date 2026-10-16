"""基于实际 API 工作流的 ComfyUI 背景生成；原模板不可变。"""
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.parse import urlencode,urlparse
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from uuid import uuid4

from PIL import Image


def digest(data):return hashlib.sha256(data).hexdigest()
def save_json(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


class ComfyUIProvider:
    capability = 'background_only'
    def __init__(self,config_path,*,project_root=None,transport=None):
        self.root=Path(project_root or Path.cwd()).resolve()
        self.config=json.loads(Path(config_path).read_text(encoding='utf-8'))
        self.base=self.config['base_url'].rstrip('/')
        if urlparse(self.base).scheme not in {'http','https'}:raise ValueError('API 地址必须为 HTTP(S)')
        self.workflow_path=self.root/self.config['workflow_path']
        data=self.workflow_path.read_bytes();self.template_hash=digest(data)
        expected=self.config.get('workflow_source',{}).get('original_sha256')
        if expected and expected!=self.template_hash:raise ValueError('原始工作流哈希已改变，请明确重新配置')
        self.template=json.loads(data)
        if not isinstance(self.template,dict) or 'nodes' in self.template:raise ValueError('需要 API prompt JSON，不是编辑器节点/连线 JSON')
        self.transport=transport or self._http

    def _http(self,route,payload=None):
        body=None if payload is None else json.dumps(payload).encode('utf-8')
        request=Request(self.base+route,data=body,headers={'Content-Type':'application/json'})
        try:
            with urlopen(request,timeout=self.config.get('request_timeout_seconds',20)) as response:return response.read()
        except HTTPError as exc:
            detail=exc.read().decode('utf-8',errors='replace')
            raise RuntimeError(f'ComfyUI HTTP {exc.code} {route}: {detail[:12000]}') from exc

    def request(self,route,payload=None):return json.loads(self.transport(route,payload))

    def prepare(self,positive,negative,width,height,seed,prefix,*,object_info=None):
        if not isinstance(positive,str) or not positive.strip():raise ValueError('正向提示词不能为空')
        if any(type(v)!=int for v in (width,height,seed)) or min(width,height)<64 or width%8 or height%8 or not 0<=seed<2**64:raise ValueError('尺寸必须为8倍数，seed必须为uint64')
        graph=deepcopy(self.template)
        if any(node.get('class_type','').startswith('LoadImage') for node in graph.values()):raise ValueError('空背景流程不能包含图像加载节点')
        if any(node.get('class_type')=='TextEncodeQwenImage21' and node.get('inputs',{}).get('images') for node in graph.values()):raise ValueError('空背景流程禁止输入商品参考图')
        values={'positive':positive,'negative':negative,'width':width,'height':height,'seed':seed,'prefix':prefix}
        for key,value in values.items():
            mapping=self.config['mapping'][key];node=graph.get(mapping['node'])
            if not node or node.get('class_type')!=mapping['class_type'] or mapping['input'] not in node.get('inputs',{}):raise ValueError('工作流映射失效: '+key)
            if object_info is not None:
                definition=object_info.get(node['class_type'])
                if not definition:raise ValueError('远程缺少节点: '+node['class_type'])
                inputs=definition.get('input',{});declared={**inputs.get('required',{}),**inputs.get('optional',{})}
                if mapping['input'] not in declared:raise ValueError('远程节点不支持映射参数: '+key)
                rules=declared[mapping['input']][1] if len(declared[mapping['input']])>1 else {}
                if type(value)==int and (value<rules.get('min',value) or value>rules.get('max',value)):raise ValueError('参数超出真实节点范围: '+key)
            node['inputs'][mapping['input']]=value
        if self.config['output_node'] not in graph:raise ValueError('输出节点不存在')
        return graph

    def generate(self,prompt,negative,*,width,height,seed,output_dir):
        out=Path(output_dir).resolve()
        if out.exists() and any(out.iterdir()):raise ValueError('输出目录非空，禁止覆盖任务历史')
        out.mkdir(parents=True,exist_ok=True)
        record={'provider':'comfyui','status':'preparing','base_url':self.base,'prompt':prompt,'negative_prompt':negative,
                'seed':seed,'requested_size_px':[width,height],'workflow_template_sha256':self.template_hash,
                'workflow_source':self.config.get('workflow_source'),'prompt_id':None,'started_at_utc':datetime.now(timezone.utc).isoformat(),
                'product_image_sent_to_AI':False,'human_review_status':'pending','background_content_verified':False}
        start=time.monotonic();client_id=str(uuid4())
        try:
            info=self.request('/object_info')
            graph=self.prepare(prompt,negative,width,height,seed,'phase3a_background_'+client_id,object_info=info)
            data=json.dumps(graph,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
            record['submitted_workflow_sha256']=digest(data);save_json(out/'submitted_workflow.json',graph)
            record['model_nodes']={key:node for key,node in graph.items() if 'Loader' in node['class_type']}
            submission=self.request('/prompt',{'prompt':graph,'client_id':client_id})
            save_json(out/'submission.json',submission)
            if submission.get('error') or submission.get('node_errors') or not submission.get('prompt_id'):raise RuntimeError('工作流提交失败: '+json.dumps(submission,ensure_ascii=False))
            pid=submission['prompt_id'];record['prompt_id']=pid;record['status']='submitted'
            save_json(out/'execution.json',record)
            print('ComfyUI submitted '+pid,flush=True)
            while True:
                if time.monotonic()-start>self.config.get('timeout_seconds',1800):
                    raise TimeoutError('等待任务超时；任务可能仍在远程执行，未全局interrupt其他用户任务。prompt_id='+pid)
                history=self.request('/history/'+pid)
                if pid in history:
                    item=history[pid];save_json(out/'history.json',item)
                    status=item.get('status',{})
                    if status.get('status_str')=='error' or any(message[0] in {'execution_error','execution_interrupted'} for message in status.get('messages',[])):
                        raise RuntimeError('远程执行失败: '+json.dumps(status,ensure_ascii=False))
                    if status.get('completed'):
                        if status.get('status_str')!='success':raise RuntimeError('远程任务终止但未成功')
                        images=item.get('outputs',{}).get(self.config['output_node'],{}).get('images',[])
                        if len(images)!=1:raise RuntimeError('预期配置输出节点返回一张图片，实际 '+str(len(images)))
                        image=images[0]
                        if image.get('type')!='output':raise RuntimeError('拒绝将临时/输入图片冒充生成输出')
                        raw=self.transport('/view?'+urlencode({key:image.get(key,'') for key in ('filename','subfolder','type')}),None)
                        with Image.open(io.BytesIO(raw)) as opened:
                            opened.load()
                            if opened.size!=(width,height):raise RuntimeError('生成图片尺寸与请求不符')
                            if opened.format!='PNG':raise RuntimeError('当前工作流需要PNG输出')
                        (out/'background.png').write_bytes(raw)
                        record.update(status='succeeded',image=image,background_sha256=digest(raw),actual_size_px=[width,height])
                        break
                time.sleep(self.config.get('poll_seconds',2))
        except Exception as exc:
            record.update(status='failed',error={'type':type(exc).__name__,'message':str(exc)})
            raise
        finally:
            record['elapsed_seconds']=time.monotonic()-start
            save_json(out/'execution.json',record)
        return out/'background.png',record
