import json,tempfile,unittest
from pathlib import Path

import numpy as np
from PIL import Image

from product_studio.segmentation.pipeline import segment,load_result
from product_studio.segmentation.base import MaskPrediction
from product_studio.segmentation.repair import repair_asset,local_repair
from product_studio.segmentation.confirmation import record_structure_confirmation
from product_studio.core.schemas import ProductSpec,EvidenceStatus
from product_studio.core.asset_binding import file_sha256


class StructureConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]);self.root=Path(self.temp.name)
        self.source=self.root/'source.png';Image.fromarray(np.full((50,100,3),240,np.uint8)).save(self.source)
        class Fixture:
            def predict(self,rgb):return MaskPrediction(np.full(rgb.shape[:2],255,np.uint8),{'provider':'synthetic_fixture'})
        segment(self.source,(0,0,50,50),'left',self.root/'initial',Fixture())
        mask=np.full((50,100),255,np.uint8)
        uncertain=[{'bbox_source_px':[10,10,20,20],'status':'requires_physical_confirmation'},
                   {'bbox_source_px':[30,30,5,5],'status':'requires_physical_confirmation'}]
        repair_asset(self.root/'initial/segmentation_result.json',(0,0,50,50),self.root/'parent',external=mask,uncertain_regions=uncertain)
        edit=np.zeros_like(mask);edit[13:27,13:27]=255
        repair_asset(self.root/'parent/segmentation_result.json',(10,10,20,20),self.root/'child',editable=edit,external=np.zeros_like(mask))
        self.result=self.root/'child/segmentation_result.json'
        parent=json.loads((self.root/'parent/segmentation_result.json').read_text(encoding='utf-8'))
        self.confirmation={key:parent['binding'][key] for key in ('source_id','source_sha256','instance_id')}
        self.confirmation.update({'reviewer':'UNIT_TEST_USER_NOT_REAL_REVIEW','fact_type':'physical_structure_confirmation',
                                  'new_status':'human_confirmed_opening','confirmation_text':'user confirms true through-hole',
                                  'region':[10,10,20,20],'previous_region':[10,10,20,20],
                                  'parent_mask_version':parent['binding']['mask_version']})
    def tearDown(self):self.temp.cleanup()
    def confirm(self):return record_structure_confirmation(self.result,self.confirmation,fact_key='opening')

    def test_human_confirmed_fact_without_mask_approval(self):
        self.confirm();spec=ProductSpec.from_dict(json.loads((self.root/'child/product_spec.json').read_text(encoding='utf-8')))
        self.assertEqual(spec.verified_facts['opening'].status,EvidenceStatus.HUMAN_VERIFIED)
        self.assertEqual(spec.product_mask.status,EvidenceStatus.ESTIMATED)
        self.assertEqual(spec.human_review_status,'partially_reviewed')
        self.assertEqual(load_result(self.result)[1]['asset_human_review_status'],'pending')

    def test_uncertain_only_matching_region_resolved(self):
        _,report=self.confirm();self.assertEqual(len(report['uncertain_regions']),1)
        self.assertEqual(report['uncertain_regions'][0]['bbox_source_px'],[30,30,5,5])
        self.assertTrue(report['resolved_regions'][0]['human_verified_opening'])
        self.assertFalse(report['resolved_regions'][0]['mask_boundary_human_verified'])

    def test_parent_audit_preserved_and_version_linked(self):
        parentmask=self.root/'parent/alpha_mask.png';parentreport=self.root/'parent/repair_report.json'
        before=(file_sha256(parentmask),file_sha256(parentreport))
        _,report=self.confirm();self.assertEqual(before,(file_sha256(parentmask),file_sha256(parentreport)))
        self.assertEqual(file_sha256(parentreport),file_sha256(self.root/'child/parent_repair_report.json'))
        audit=report['revision_audit'];self.assertNotEqual(audit['parent_mask_version'],audit['new_mask_version'])
        self.assertEqual(audit['parent_mask_version'],self.confirmation['parent_mask_version'])
        self.assertEqual(audit['changed_region_bbox'],[13,13,14,14])

    def test_cross_instance_confirmation_rejected(self):
        self.confirmation['instance_id']='right'
        with self.assertRaises(ValueError):self.confirm()

    def test_stale_parent_version_rejected(self):
        self.confirmation['parent_mask_version']='0'*64
        with self.assertRaises(ValueError):self.confirm()

    def test_unmatched_uncertainty_rejected(self):
        self.confirmation['previous_region']=[0,0,1,1]
        with self.assertRaises(ValueError):self.confirm()

    def test_confirmation_cannot_overwrite_record(self):
        self.confirm()
        with self.assertRaises(ValueError):self.confirm()

    def test_missing_named_actor_rejected(self):
        self.confirmation['reviewer']=''
        with self.assertRaises(ValueError):self.confirm()

    def test_new_initialization_keeps_protected_edges(self):
        rgb=np.full((30,30,3),40,np.uint8);rgb[8:22,8:22]=245
        alpha=np.full((30,30),255,np.uint8)
        edit=np.zeros_like(alpha);edit[7:23,7:23]=255
        fg=255-edit;bg=np.zeros_like(alpha);bg[12:18,12:18]=255
        after,_,_=local_repair(rgb,alpha,(0,0,30,30),editable=edit,foreground=fg,background=bg,unknown_initialization='probable_background')
        np.testing.assert_array_equal(after[fg>0],alpha[fg>0]);self.assertEqual(after[15,15],0)


if __name__=='__main__':unittest.main()
