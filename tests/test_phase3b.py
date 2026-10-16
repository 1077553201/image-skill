import io,json,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image

from product_studio.generation.candidates import load_configuration,make_plan,BackgroundCache,compose_configuration
from product_studio.generation.candidate_quality import background_metrics,select_candidates,evaluate_candidate
from product_studio.generation.compositor import compose_asset
from product_studio.providers.comfyui import ComfyUIProvider,save_json,digest
from product_studio.segmentation.pipeline import segment
from product_studio.segmentation.base import MaskPrediction
from product_studio.core.asset_binding import file_sha256

ROOT=Path(__file__).resolve().parents[1]


class SceneTests(unittest.TestCase):
    def setUp(self):
        self.config,self.presets=load_configuration(ROOT/'configs/phase3b_product_set.json',ROOT/'configs/scene_presets.json')
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.path=Path(self.temp.name)/'config.json'
    def tearDown(self):self.temp.cleanup()
    def load_changed(self):
        save_json(self.path,self.config);return load_configuration(self.path,ROOT/'configs/scene_presets.json')
    def test_two_reusable_presets_with_no_floor(self):
        self.assertEqual(len(self.presets),2)
        self.assertTrue(all(not p['allow_floor'] and not p['allow_visible_horizon'] for p in self.presets.values()))
    def test_unknown_view_not_silently_adapted(self):
        self.config['assets'][0]['visible_view']='back'
        with self.assertRaises(ValueError):self.load_changed()
    def test_duplicate_instances_rejected(self):
        self.config['assets'][1]['instance_id']=self.config['assets'][0]['instance_id']
        with self.assertRaises(ValueError):self.load_changed()
    def test_stable_four_tasks_different_seeds(self):
        bindings={a['instance_id']:{'source_sha256':'a'*64} for a in self.config['assets']}
        first=make_plan(self.config,self.presets,None,bindings)
        self.assertEqual(first,make_plan(self.config,self.presets,None,bindings))
        self.assertEqual(len(first),4);self.assertEqual(len({t['seed'] for t in first}),4)
        self.assertIn('not automatic visual classification',first[0]['view_evidence'])
    def test_output_size_automatically_fits_product_without_stretch(self):
        rgba=np.full((1000,1000,4),255,np.uint8)
        result=compose_configuration(self.config['assets'][0],self.presets['abstract_premium'],rgba,[512,512])
        self.assertLess(result['scale'],.5);self.assertNotIn('scale_x',result);self.assertNotIn('scale_y',result)


class FakeProvider:
    base='http://mock-not-real';template_hash='fixture';config={'output_node':'output'}
    def __init__(self):self.calls=0;self.fail=False;self.history={}
    def prepare(self,prompt,negative,width,height,seed,prefix):return {'seed':seed,'prompt':prompt,'negative':negative,'size':[width,height],'prefix':prefix}
    def generate(self,prompt,negative,*,width,height,seed,output_dir):
        self.calls+=1;out=Path(output_dir);out.mkdir(parents=True)
        record={'status':'failed' if self.fail else 'succeeded','prompt_id':'mock-3b','seed':seed,'prompt':prompt,'negative_prompt':negative,'provider':'mock-not-real'}
        if self.fail:save_json(out/'execution.json',record);raise RuntimeError('synthetic failure')
        image=out/'background.png';Image.new('RGB',(width,height),'gray').save(image)
        record['background_sha256']=file_sha256(image);save_json(out/'execution.json',record)
        return image,record
    def request(self,route):return self.history
    def transport(self,route,payload):
        raw=io.BytesIO();Image.new('RGB',(64,64),'gray').save(raw,format='PNG');return raw.getvalue()


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        self.provider=FakeProvider();self.cache=BackgroundCache(self.provider,self.root)
        self.task={'instance_id':'left','mode':'preview','prompt':'empty wall','negative':'objects','width':64,'height':64,'seed':1,
                   'source_binding':{'source_id':'source1','source_sha256':'a'*64,'mask_version':'b'*64}}
    def tearDown(self):self.temp.cleanup()
    def test_success_reused_no_duplicate_submission(self):
        _,_,first=self.cache.get(self.task);_,_,second=self.cache.get(self.task)
        self.assertFalse(first['cache_hit']);self.assertTrue(second['cache_hit']);self.assertEqual(self.provider.calls,1)
    def test_seed_and_instance_isolation(self):
        key=self.cache.key(self.task)
        self.assertNotEqual(key,self.cache.key({**self.task,'seed':2}))
        self.assertNotEqual(key,self.cache.key({**self.task,'instance_id':'right'}))
        self.assertNotEqual(key,self.cache.key({**self.task,'mode':'strict'}))
    def test_tampered_success_not_resubmitted(self):
        image,_,_=self.cache.get(self.task);image.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):self.cache.get(self.task)
        self.assertEqual(self.provider.calls,1)
    def test_failed_task_pending_no_automatic_retry(self):
        self.provider.fail=True
        with self.assertRaises(RuntimeError):self.cache.get(self.task)
        with self.assertRaises(RuntimeError):self.cache.get(self.task)
        self.assertEqual(self.provider.calls,1)
        self.assertTrue((self.root/self.cache.key(self.task)/'failure.json').exists())
    def test_recover_known_completed_prompt_without_new_job(self):
        self.provider.fail=True
        with self.assertRaises(RuntimeError):self.cache.get(self.task)
        attempt=self.root/self.cache.key(self.task)/'attempt_001';prior=(attempt/'execution.json').read_bytes()
        graph={'seed':1};save_json(attempt/'submitted_workflow.json',graph)
        self.provider.history={'mock-3b':{'status':{'status_str':'success','completed':True},'prompt':[0,'mock-3b',graph],
                                         'outputs':{'output':{'images':[{'filename':'x.png','type':'output'}]}}}}
        image,record,meta=self.cache.get(self.task)
        self.assertTrue(meta['recovered']);self.assertTrue(image.exists());self.assertTrue(record['recovery_did_not_resubmit'])
        self.assertEqual(prior,(attempt/'execution.json').read_bytes());self.assertEqual(self.provider.calls,1)
    def test_missing_prompt_id_does_not_resubmit(self):
        self.provider.fail=True
        with self.assertRaises(RuntimeError):self.cache.get(self.task)
        path=self.root/self.cache.key(self.task)/'attempt_001/execution.json';record=json.loads(path.read_text());record['prompt_id']=None;save_json(path,record)
        with self.assertRaises(RuntimeError):self.cache.get(self.task)
        self.assertEqual(self.provider.calls,1)


def candidate(name,score,hard=True,risks=None):return {'candidate_id':name,'quality':{'hard_pass':hard,'score':score,'risk_flags':risks or []}}


class RankingTests(unittest.TestCase):
    def test_heuristic_ranking_and_pending(self):
        result=select_candidates([candidate('A',40),candidate('B',80)])
        self.assertEqual(result['recommended']['candidate_id'],'B');self.assertEqual(result['human_review_status'],'pending')
    def test_hard_failure_cannot_be_preferred(self):
        result=select_candidates([candidate('A',100,False),candidate('B',20)],preferred_order=['A','B'])
        self.assertEqual(result['recommended']['candidate_id'],'B');self.assertEqual(result['rejected'],['A'])
    def test_explicit_fallback_not_advanced_success(self):
        result=select_candidates([candidate('A',50,risks=['floor'])],fallback={'image':'old_studio.png'})
        self.assertEqual(result['recommended_kind'],'fallback_premium_studio');self.assertFalse(result['advanced_scene_success'])
    def test_all_failed_no_fake_recommendation(self):
        result=select_candidates([candidate('A',0,False)])
        self.assertIsNone(result['recommended']);self.assertEqual(result['recommended_kind'],'none')
    def test_manual_order_not_approval(self):
        result=select_candidates([candidate('A',90),candidate('B',20)],preferred_order=['B','A'])
        self.assertEqual(result['recommended']['candidate_id'],'B');self.assertEqual(result['status'],'requires_review')
    def test_horizontal_line_is_risk_not_semantic_verification(self):
        clean=np.full((256,256,3),100,np.uint8);line=clean.copy();line[190:,:]=210
        a=background_metrics(clean,[.1,.1,.8,.8]);b=background_metrics(line,[.1,.1,.8,.8])
        self.assertGreater(b['horizontal_line_risk'],a['horizontal_line_risk']);self.assertIn('text_or_logo',b['cannot_verify'])
    def test_low_contrast_floor_edge_is_only_risk(self):
        image=np.full((256,256,3),100,np.uint8);image[200:,:]=112
        self.assertGreater(background_metrics(image,[.1,.1,.8,.8])['horizontal_line_risk'],.4)


class HardQualityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        source=self.root/'source.png';Image.new('RGB',(80,80),'blue').save(source)
        class Fixture:
            def predict(self,rgb):
                alpha=np.full(rgb.shape[:2],255,np.uint8);alpha[20:30,20:30]=0
                return MaskPrediction(alpha,{'provider':'synthetic_quality_fixture'})
        segment(source,(10,10,50,50),'item',self.root/'asset',Fixture())
        background=self.root/'bg.png';Image.new('RGB',(128,128),'gray').save(background)
        compose_asset(self.root/'asset/segmentation_result.json',background,self.root/'composite',
                      {'mode':'preview','instance_id':'item','scale':1,'output_size_px':[128,128]},
                      {'status':'succeeded','background_sha256':file_sha256(background),'provider':'synthetic_fixture'})
        self.preset=json.loads((ROOT/'configs/scene_presets.json').read_text(encoding='utf-8'))['presets']['abstract_premium']
    def tearDown(self):self.temp.cleanup()
    def test_valid_preview_quality_never_approved(self):
        result=evaluate_candidate(self.root/'composite',self.preset)
        self.assertTrue(result['hard_pass']);self.assertEqual(result['human_review_status'],'pending')
    def test_tampered_output_rejected(self):
        Image.new('RGB',(128,128),'red').save(self.root/'composite/final.png')
        self.assertFalse(evaluate_candidate(self.root/'composite',self.preset)['hard_pass'])
    def test_instance_binding_mismatch_rejected(self):
        path=self.root/'composite/composite_manifest.json';value=json.loads(path.read_text(encoding='utf-8'));value['source_binding']['instance_id']='another';save_json(path,value)
        self.assertFalse(evaluate_candidate(self.root/'composite',self.preset)['hard_pass'])


if __name__=='__main__':unittest.main()
