from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from PIL import Image

from product_studio.creative.content_contract import task_contract,validate_consumer_text
from product_studio.creative.facts import resolve_product_facts
from product_studio.creative.campaign import campaign_request
from product_studio.core.asset_binding import file_sha256
from product_studio.segmentation.pipeline import segment
from product_studio.segmentation.base import MaskPrediction

ROOT=Path(__file__).resolve().parents[1]


class ContentContractTests(unittest.TestCase):
    def test_edit_route_cannot_become_strict(self):
        from product_studio.core.task_planner import generation_route
        with self.assertRaises(ValueError):generation_route('image_guided_creative_edit','strict_product',mask_review_valid=True)
        self.assertFalse(generation_route('image_guided_creative_edit','concept_creative')['identity_verified'])
    def test_unreviewed_source_cannot_become_strict(self):
        from product_studio.core.task_planner import generation_route
        with self.assertRaises(ValueError):generation_route('background_only','strict_product')
        self.assertEqual(generation_route('background_only','source_preserving_preview')['asset_human_review_status'],'pending')
    def test_long_internal_notes_cannot_become_consumer_copy(self):
        analysis={'consumer_copy':{'studio_photo':{'headline':'Black. Beautifully simple.'}},
                  'copy':{'studio_photo':{'headline':'Skill pipeline engineering'}},
                  'internal_notes':{'context':'Pipeline Agent Mask Evidence 项目开发 '*1000}}
        got=task_contract({},analysis)
        self.assertEqual(got['copy'],analysis['consumer_copy']);self.assertEqual(got['internal_notes'],analysis['internal_notes'])
        self.assertNotIn('Pipeline',str(got['consumer_copy']))
    def test_internal_copy_rejected(self):
        for text in ['Mask review passed','Evidence pipeline','源像素保留','仅展示原图中的内容','Details from the original photograph']:
            with self.subTest(text=text),self.assertRaises(ValueError):validate_consumer_text(text)
    def test_explicit_disclosure_is_separate_authorization(self):
        validate_consumer_text('Mask review',{'allow_production_disclosure':True,'user_statement':'Please display the production review status'})
        with self.assertRaises(ValueError):validate_consumer_text('Mask review',{'allow_production_disclosure':True})
    def test_development_task_not_advertising_job(self):
        with self.assertRaises(ValueError):task_contract({'task_intent':'project_development'},{})


class FactInheritanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        image=self.root/'source.png';Image.new('RGB',(80,80),'blue').save(image)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic'})
        self.result=segment(image,(5,5,65,65),'selected',self.root/'asset',Fixture());self.binding=self.result['binding']
        self.path=self.root/'asset/segmentation_result.json';self.spec_path=self.root/'asset/product_spec.json'
        self.spec=json.loads(self.spec_path.read_text(encoding='utf-8'));b=self.binding
        record={k:b[k] for k in ('source_id','source_sha256','instance_id')};record.update(new_mask_version=b['mask_version'],reviewer='actual test reviewer',fact_type='physical_structure_confirmation')
        rp=self.root/'confirmation.json';rp.write_text(json.dumps(record),encoding='utf-8')
        value={k:b[k] for k in ('source_id','source_sha256','instance_id')};value.update(physical_structure='through_hole',human_verified_opening=True,confirmation_record=str(rp),confirmation_sha256=file_sha256(rp),region=[20,20,8,8])
        self.spec['verified_facts']['opening']={'value':value,'status':'human_verified','reviewer':record['reviewer'],'sources':[b['source_id']],'method':'user_confirmation'}
        self.spec_path.write_text(json.dumps(self.spec),encoding='utf-8')
        self.request=campaign_request({'product_id':'campaign_alias','product_asset':str(self.path)})
    def tearDown(self):self.temp.cleanup()
    def resolve(self,analysis=None):return resolve_product_facts(self.path,self.request,analysis or {},self.binding)
    def test_confirmed_opening_inherited_with_canonical_product(self):
        f=self.resolve();self.assertEqual(f['facts']['opening']['status'],'human_verified');self.assertTrue(f['facts']['opening']['value']['human_verified_opening'])
        self.assertEqual(f['canonical_product_id'],self.spec['product_id']);self.assertEqual(f['inherited_fact_ids'],['opening'])
    def test_visual_unknown_cannot_downgrade_confirmation(self):
        f=self.resolve({'facts':{'opening':{'value':None,'status':'unknown','sources':[]}}})
        self.assertEqual(f['facts']['opening']['status'],'human_verified');self.assertTrue(f['resolution_decisions'])
    def test_conflicting_observation_rejected(self):
        with self.assertRaisesRegex(ValueError,'conflicts'):self.resolve({'facts':{'opening':{'value':False,'status':'observed','sources':[self.binding['source_id']],'method':'visual_observation'}}})
    def test_other_instance_confirmation_cannot_inherit(self):
        self.spec['verified_facts']['opening']['value']['instance_id']='other'
        self.spec_path.write_text(json.dumps(self.spec),encoding='utf-8')
        with self.assertRaises(ValueError):self.resolve()
    def test_stale_confirmation_hash_rejected(self):
        (self.root/'confirmation.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash'):self.resolve()
    def test_mask_version_mismatch_rejected(self):
        binding={**self.binding,'mask_version':'f'*64}
        with self.assertRaises(ValueError):resolve_product_facts(self.path,self.request,{},binding)
