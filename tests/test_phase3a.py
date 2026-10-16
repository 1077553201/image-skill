import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

from product_studio.providers.comfyui import ComfyUIProvider
from product_studio.generation.compositor import composite_arrays,load_foreground
from product_studio.segmentation.pipeline import segment,review_mask
from product_studio.segmentation.base import MaskPrediction

ROOT=Path(__file__).resolve().parents[1]


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        self.calls=[]
        self.provider=ComfyUIProvider(ROOT/'configs/comfyui_phase3a.json',project_root=ROOT,transport=self.transport)
    def tearDown(self):self.temp.cleanup()
    def transport(self,route,payload=None):
        self.calls.append((route,payload))
        if route=='/object_info':return (ROOT/'reports/phase3a/object_info.json').read_bytes()
        if route=='/prompt':return json.dumps({'prompt_id':'mock-not-real'}).encode()
        if route.startswith('/history/'):
            return json.dumps({'mock-not-real':{'status':{'status_str':'success','completed':True},'outputs':{'461':{'images':[{'filename':'mock.png','subfolder':'','type':'output'}]}}}}).encode()
        image=Image.new('RGB',(64,64),'gray');data=io.BytesIO();image.save(data,format='PNG');return data.getvalue()
    def generate(self):return self.provider.generate('empty wall','objects',width=64,height=64,seed=1,output_dir=self.root/'out')
    def test_actual_template_mapping_without_mutation(self):
        before=json.dumps(self.provider.template,sort_keys=True)
        graph=self.provider.prepare('new positive','new negative',1024,768,37,'unique')
        self.assertEqual(graph['452']['inputs']['prompt'],'new positive');self.assertEqual(graph['452']['inputs']['negative_prompt'],'new negative')
        self.assertEqual(graph['456']['inputs']['height'],768);self.assertEqual(graph['458']['inputs']['seed'],37)
        self.assertEqual(json.dumps(self.provider.template,sort_keys=True),before)
    def test_bad_mapping_rejected(self):
        self.provider.config['mapping']['seed']['node']='not-real'
        with self.assertRaises(ValueError):self.provider.prepare('x','',64,64,1,'x')
    def test_success_mock_is_explicitly_separate(self):
        image,record=self.generate();self.assertTrue(image.exists());self.assertEqual(record['prompt_id'],'mock-not-real')
        self.assertEqual(record['status'],'succeeded');self.assertFalse(record['background_content_verified'])
    def test_submit_error_saved(self):
        old=self.transport
        self.provider.transport=lambda r,p=None:json.dumps({'error':'invalid'}).encode() if r=='/prompt' else old(r,p)
        with self.assertRaises(RuntimeError):self.generate()
        self.assertEqual(json.loads((self.root/'out/execution.json').read_text(encoding='utf-8'))['status'],'failed')
    def test_history_error(self):
        old=self.transport
        self.provider.transport=lambda r,p=None:json.dumps({'mock-not-real':{'status':{'status_str':'error','messages':[['execution_error',{}]]}}}).encode() if r.startswith('/history/') else old(r,p)
        with self.assertRaises(RuntimeError):self.generate()
    def test_timeout_saved_without_global_interrupt(self):
        self.provider.config['timeout_seconds']=-1
        with self.assertRaises(TimeoutError):self.generate()
        self.assertFalse(any(route=='/interrupt' for route,_ in self.calls))
    def test_invalid_image_not_success(self):
        old=self.transport;self.provider.transport=lambda r,p=None:b'not an image' if r.startswith('/view?') else old(r,p)
        with self.assertRaises(OSError):self.generate()
        self.assertEqual(json.loads((self.root/'out/execution.json').read_text(encoding='utf-8'))['status'],'failed')
    def test_invalid_size_seed(self):
        for width,seed in [(65,1),(64,-1),(64,2**64)]:
            with self.assertRaises(ValueError):self.provider.prepare('x','',width,64,seed,'x')
    def test_existing_output_not_overwritten(self):
        self.generate()
        with self.assertRaises(ValueError):self.generate()
    def test_background_cannot_load_product_image(self):
        self.provider.template['forbidden']={'class_type':'LoadImage','inputs':{'image':'product.png'}}
        with self.assertRaises(ValueError):self.provider.prepare('x','',64,64,1,'x')
    def test_reference_image_input_rejected(self):
        self.provider.template['452']['inputs']['images']=[['example',0]]
        with self.assertRaises(ValueError):self.provider.prepare('x','',64,64,1,'x')


class CompositeTests(unittest.TestCase):
    def setUp(self):
        self.rgba=np.zeros((50,50,4),np.uint8);self.rgba[:,:,:3]=[250,20,35]
        self.rgba[10:40,10:40,3]=255;self.rgba[20:30,20:30,3]=0
        self.bg=np.full((100,100,3),(12,90,150),np.uint8)
    def test_hole_shows_new_background_and_rgb_exact(self):
        out,a,_,t=composite_arrays(self.rgba,self.bg)
        tx,ty=int(t['matrix_source_to_output'][0][2]),int(t['matrix_source_to_output'][1][2])
        np.testing.assert_array_equal(out[25+ty,25+tx],self.bg[25+ty,25+tx])
        np.testing.assert_array_equal(out[15+ty,15+tx],self.rgba[15,15,:3])
        self.assertFalse(t['perspective'])
    def test_soft_alpha_correct(self):
        self.rgba[15,15,3]=128;out,_,_,t=composite_arrays(self.rgba,self.bg)
        tx,ty=int(t['matrix_source_to_output'][0][2]),int(t['matrix_source_to_output'][1][2])
        expected=np.rint(self.rgba[15,15,:3]*np.float64(128/255)+self.bg[0,0]*(127/255)).astype(np.uint8)
        np.testing.assert_array_equal(out[15+ty,15+tx],expected)
    def test_uniform_scale_and_hidden_rgb_no_halo(self):
        first=composite_arrays(self.rgba,self.bg,scale=.85)[0]
        self.rgba[self.rgba[:,:,3]==0,:3]=[0,255,0]
        second=composite_arrays(self.rgba,self.bg,scale=.85)[0]
        np.testing.assert_array_equal(first,second)
    def test_subject_clipping_rejected(self):
        with self.assertRaises(ValueError):composite_arrays(self.rgba,self.bg,scale=4)
    def test_empty_mask_rejected(self):
        self.rgba[:,:,3]=0
        with self.assertRaises(ValueError):composite_arrays(self.rgba,self.bg)
    def test_only_optional_backdrop_shadow(self):
        _,_,a,_=composite_arrays(self.rgba,self.bg,shadow={'mode':'backdrop'})
        self.assertTrue(np.any(a))
        with self.assertRaises(ValueError):composite_arrays(self.rgba,self.bg,shadow={'mode':'ground'})


class ReviewGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        source=self.root/'source.png';Image.new('RGB',(100,100),'blue').save(source)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic_gate_fixture'})
        self.result=segment(source,(10,10,40,40),'left',self.root/'asset',Fixture())
        self.path=self.root/'asset/segmentation_result.json'
    def tearDown(self):self.temp.cleanup()
    def test_preview_not_promoted_to_strict(self):
        self.assertEqual(load_foreground(self.path,mode='preview',expected_instance='left')[2]['mode'],'preview')
        with self.assertRaises(ValueError):load_foreground(self.path,mode='strict',expected_instance='left')
    def test_other_instance_rejected(self):
        with self.assertRaises(ValueError):load_foreground(self.path,mode='preview',expected_instance='right')
    def test_valid_review_then_changed_rgba_rejected(self):
        b=self.result['binding'];review_mask(self.path,reviewer='UNIT_TEST_NOT_USER',expected_source_id=b['source_id'],expected_instance_id='left',expected_version=b['mask_version'])
        self.assertTrue(load_foreground(self.path,mode='strict',expected_instance='left')[2]['mask_review_valid'])
        path=self.root/'asset/product_rgba.png'
        with Image.open(path) as im:a=np.asarray(im).copy()
        a[20,20,0]=17;Image.fromarray(a).save(path)
        with self.assertRaises(ValueError):load_foreground(self.path,mode='strict',expected_instance='left')


if __name__=='__main__':unittest.main()
