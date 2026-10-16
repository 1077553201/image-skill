import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image

from product_studio.asset_bundle import export_asset,import_asset
from product_studio.configuration import platform_preset,provider_config
from product_studio.creative.executor import execute
from product_studio.generation.compositor import load_foreground
from product_studio.segmentation.pipeline import segment,review_mask
from product_studio.segmentation.base import MaskPrediction

ROOT=Path(__file__).resolve().parents[1]


class PortableRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        image=self.root/'input.png';Image.new('RGB',(100,100),'#326385').save(image)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic_fixture'})
        self.result=segment(image,(10,10,70,70),'item',self.root/'original',Fixture())
    def tearDown(self):self.temp.cleanup()
    def test_bundle_preserves_version_and_strict_review(self):
        b=self.result['binding'];review_mask(self.root/'original/segmentation_result.json',reviewer='test reviewer',expected_source_id=b['source_id'],expected_instance_id='item',expected_version=b['mask_version'])
        export_asset(self.root/'original/segmentation_result.json',self.root/'bundle')
        path=import_asset(self.root/'bundle/asset_bundle.json',self.root/'import')
        _,new,gate=load_foreground(path,mode='strict',expected_instance='item')
        self.assertEqual(new['binding']['mask_version'],b['mask_version']);self.assertTrue(gate['mask_review_valid'])
        self.assertEqual((self.root/'original/alpha_mask.png').read_bytes(),(path.parent/'alpha_mask.png').read_bytes())
    def test_bundle_tamper_is_rejected(self):
        export_asset(self.root/'original/segmentation_result.json',self.root/'bundle')
        (self.root/'bundle/alpha_mask.png').write_bytes(b'changed')
        with self.assertRaises(ValueError):import_asset(self.root/'bundle/asset_bundle.json',self.root/'import')
    def test_bundle_escape_is_rejected(self):
        m=export_asset(self.root/'original/segmentation_result.json',self.root/'bundle');m['files']['../input.png']='0'*64
        p=self.root/'bundle/asset_bundle.json';p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):import_asset(p,self.root/'import')
    def test_preview_not_upgraded_by_export(self):
        export_asset(self.root/'original/segmentation_result.json',self.root/'bundle')
        path=import_asset(self.root/'bundle/asset_bundle.json',self.root/'import')
        with self.assertRaises(ValueError):load_foreground(path,mode='strict',expected_instance='item')
    def test_packaged_presets_without_checkout(self):
        self.assertEqual(platform_preset(self.root/'unrelated','generic')['id'],'generic')
    def test_no_implicit_development_service(self):
        with patch.dict('os.environ',{},clear=True),self.assertRaisesRegex(ValueError,'COMFYUI_BASE_URL'):
            provider_config(None,self.root)
    def test_installed_api_accepts_explicit_output_elsewhere(self):
        export_asset(self.root/'original/segmentation_result.json',self.root/'bundle')
        r={'product_id':'item','product_asset':'bundle/asset_bundle.json','output_count':1,'shot_types':['white_hero'],'generation_budget':{'max_new_backgrounds':0}}
        p=self.root/'request.json';p.write_text(json.dumps(r));out=self.root/'arbitrary/output'
        state=execute(self.root,p,portable=True,output_dir=out,prepare_only=True)
        self.assertEqual(state['status'],'needs_agent_analysis');self.assertTrue((out/'agent_handoff.json').is_file())
    def test_explicit_output_required(self):
        p=self.root/'request.json';p.write_text(json.dumps({'product_id':'x','product_asset':'missing'}))
        with self.assertRaisesRegex(ValueError,'explicit'):execute(self.root,p,portable=True)
