from contextlib import redirect_stdout,redirect_stderr
import io,json
from pathlib import Path
import sys,tempfile,unittest

import numpy as np
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from product_studio.core.schemas import ProductSpec,EvidenceStatus
from product_studio.core.task_planner import Strategy,OutputRequest,plan_task
from product_studio.segmentation.base import MaskPrediction,SegmentationProvider
from product_studio.segmentation.pipeline import segment,correct_mask,review_mask,load_result,read_spec
from product_studio.segmentation.mask_processing import (place_roi_alpha,import_external_mask,make_rgba,select_by_points)
from product_studio.segmentation.provider import BiRefNetLiteProvider
from product_studio.segmentation.cli import main


class TruthFixture(SegmentationProvider):
    def __init__(self,alpha):self.alpha=alpha
    def predict(self,rgb):
        if self.alpha.shape!=rgb.shape[:2]:raise ValueError("fixture shape mismatch")
        return MaskPrediction(self.alpha.copy(),{"provider":"synthetic_truth_fixture","actual_model_execution":False})


class SegmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.root=Path(self.temp.name)
        self.rgb=np.full((100,160,3),230,np.uint8)
        self.rgb[20:80,10:70]=(30,60,90);self.rgb[20:80,90:150]=(240,240,240)
        self.source=self.root/"原图.png";Image.fromarray(self.rgb).save(self.source)
        self.roi=(0,10,80,80)
        self.alpha=np.zeros((80,80),np.uint8);self.alpha[10:70,10:70]=255;self.alpha[30:50,30:50]=0
    def tearDown(self):self.temp.cleanup()
    def create(self,out="asset",*,instance="left",alpha=None):
        return segment(self.source,self.roi,instance,self.root/out,TruthFixture(self.alpha if alpha is None else alpha))

    def test_rgba_preserves_all_original_rgb_and_maps_roi(self):
        result=self.create()
        rgba=np.asarray(Image.open(self.root/"asset/product_rgba.png"))
        np.testing.assert_array_equal(rgba[:,:,:3],self.rgb)
        expected=place_roi_alpha(self.alpha,self.roi,(160,100))
        np.testing.assert_array_equal(rgba[:,:,3],expected)
        self.assertEqual(rgba[50,40,3],0)
        self.assertEqual(rgba[30,15,3],255)
        self.assertTrue(result["rgb_policy"]["original_decoded_rgb_preserved"])

    def test_export_all_previews_raw_mask_and_original(self):
        result=self.create()
        for name in ["product_rgba.png","alpha_mask.png","mask_overlay.png","checkerboard_preview.png","dark_background_preview.png","light_background_preview.png","segmentation_result.json","raw_alpha_mask.png","source_original.png","product_spec.json"]:
            self.assertTrue((self.root/"asset"/name).is_file(),name)
        self.assertEqual(result["coordinate_system"],"source_pixels")
        self.assertEqual(result["output_size_px"],[160,100])
        self.assertEqual(result["human_review"]["status"],"pending")

    def test_same_photo_different_instances_get_different_bound_versions(self):
        left=self.create()
        right=segment(self.source,(80,10,80,80),"right",self.root/"right",TruthFixture(self.alpha))
        self.assertEqual(left["source"]["source_id"],right["source"]["source_id"])
        self.assertNotEqual(left["binding"]["mask_version"],right["binding"]["mask_version"])
        right_alpha=np.asarray(Image.open(self.root/"right/alpha_mask.png"))
        self.assertFalse(np.any(right_alpha[:,:80]))
        self.assertEqual(right["instance_id"],"right")

    def test_soft_alpha_and_multiple_disconnected_regions_are_preserved(self):
        alpha=np.zeros((80,80),np.uint8);alpha[10:30,10:30]=170;alpha[45:60,45:60]=240;alpha[9,10:30]=64
        self.create(alpha=alpha)
        saved=np.asarray(Image.open(self.root/"asset/alpha_mask.png"))
        np.testing.assert_array_equal(saved[10:90,:80],alpha)
        self.assertEqual(saved[19,15],64)

    def test_white_product_and_dark_product_not_erased_by_color(self):
        for foreground,background in [(250,245),(15,20)]:
            rgb=np.full((100,160,3),background,np.uint8);rgb[20:80,10:70]=foreground
            Image.fromarray(rgb).save(self.source)
            output=self.root/f"colors_{foreground}"
            segment(self.source,self.roi,"item",output,TruthFixture(self.alpha))
            rgba=np.asarray(Image.open(output/"product_rgba.png"))
            self.assertEqual(rgba[30,20,3],255)
            self.assertEqual(rgba[30,20,0],foreground)

    def test_external_roi_mask_import_and_correction_preserve_provenance(self):
        prior=self.create();corrected=self.alpha.copy();corrected[15:25,15:25]=0
        path=self.root/"manual.png";Image.fromarray(corrected).save(path)
        updated=correct_mask(self.root/"asset/segmentation_result.json",path,"roi",self.root/"corrected")
        self.assertNotEqual(updated["binding"]["mask_version"],prior["binding"]["mask_version"])
        self.assertEqual(updated["instance_id"],prior["instance_id"])
        self.assertEqual(updated["provider"]["provider"],"external_mask_import")
        self.assertFalse(updated["provider"]["automatic_model_executed"])
        np.testing.assert_array_equal(np.asarray(Image.open(self.root/"corrected/raw_alpha_mask.png")),np.asarray(Image.open(self.root/"asset/raw_alpha_mask.png")))

    def test_external_other_instance_mask_not_silently_cropped(self):
        wrong=np.zeros((100,160),np.uint8);wrong[20:80,90:150]=255
        path=self.root/"wrong.png";Image.fromarray(wrong).save(path)
        with self.assertRaises(ValueError):import_external_mask(path,coordinates="source",roi=self.roi,source_size=(160,100))

    def test_external_size_mismatch_not_guessed_or_resized(self):
        path=self.root/"bad.png";Image.fromarray(np.full((10,10),255,np.uint8)).save(path)
        with self.assertRaises(ValueError):import_external_mask(path,coordinates="roi",roi=self.roi,source_size=(160,100))

    def test_empty_mask_cannot_be_approved(self):
        result=self.create(alpha=np.zeros_like(self.alpha))
        self.assertEqual(result["status"],"failed")
        with self.assertRaises(ValueError):self.approve(result)

    def approve(self,result,folder="asset",**overrides):
        args={"reviewer":"UNIT_TEST_REVIEWER_NOT_REAL_USER","expected_source_id":result["binding"]["source_id"],
              "expected_instance_id":result["instance_id"],"expected_version":result["binding"]["mask_version"]}
        args.update(overrides)
        return review_mask(self.root/folder/"segmentation_result.json",**args)

    def test_explicit_review_unlocks_only_matching_mask_and_not_entire_product(self):
        result=self.create();self.approve(result)
        spec=ProductSpec.from_dict(json.loads((self.root/"asset/product_spec.json").read_text(encoding="utf-8")))
        self.assertEqual(spec.product_mask.status,EvidenceStatus.HUMAN_VERIFIED)
        self.assertEqual(spec.human_review_status,"partially_reviewed")
        self.assertEqual(plan_task(spec,OutputRequest(Strategy.ORIGINAL_COMPOSITE)).status,"planned")
        self.assertEqual(plan_task(spec,OutputRequest(Strategy.AI_BACKGROUND)).status,"blocked")

    def test_review_wrong_source_instance_version_or_missing_name_rejected(self):
        result=self.create()
        for bad in [{"expected_source_id":"other"},{"expected_instance_id":"right"},{"expected_version":"stale"},{"reviewer":""}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.approve(result,**bad)

    def test_changed_mask_or_rgba_cannot_reuse_review(self):
        result=self.create();self.approve(result)
        spec=ProductSpec.from_dict(json.loads((self.root/"asset/product_spec.json").read_text(encoding="utf-8")))
        (self.root/"asset/alpha_mask.png").write_bytes(b"changed")
        self.assertEqual(plan_task(spec,OutputRequest(Strategy.ORIGINAL_COMPOSITE)).status,"blocked")
        with self.assertRaises(ValueError):load_result(self.root/"asset/segmentation_result.json")

    def test_corrected_version_revokes_prior_mask_approval(self):
        result=self.create();self.approve(result)
        path=self.root/"mask.png";corrected=self.alpha.copy();corrected[15:25,15:25]=0;Image.fromarray(corrected).save(path)
        correct_mask(self.root/"asset/segmentation_result.json",path,"roi",self.root/"next")
        spec=ProductSpec.from_dict(json.loads((self.root/"next/product_spec.json").read_text(encoding="utf-8")))
        self.assertEqual(spec.product_mask.status,EvidenceStatus.ESTIMATED)
        self.assertNotIn("product_mask",spec.verified_facts)
        self.assertEqual(plan_task(spec,OutputRequest(Strategy.ORIGINAL_COMPOSITE)).status,"blocked")

    def test_old_studio_schema_still_loads_and_masks_are_not_upgraded(self):
        self.create();raw=json.loads((self.root/"asset/product_spec.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["schema_version"],"studio.1g.1")
        self.assertEqual(ProductSpec.from_dict(raw).product_mask.status,EvidenceStatus.ESTIMATED)

    def test_legacy_1a_spec_can_be_reused_for_selected_source(self):
        import cv2
        from product_photo.extract_structure import analyze_image
        from product_studio.core.asset_binding import file_sha256
        from product_studio.core.schemas import SourceImage
        rgb=np.full((300,300,3),255,np.uint8);cv2.circle(rgb,(150,150),100,(15,110,180),-1)
        image=self.root/"disc.png";Image.fromarray(rgb).save(image)
        raw=analyze_image(rgb[:,:,::-1].copy())[0].spec
        raw["source_image"]["sha256"]=file_sha256(image)
        old=self.root/"old.json";old.write_text(json.dumps(raw),encoding="utf-8")
        spec=read_spec(old,SourceImage("s",str(image),file_sha256(image),300,300))
        self.assertIn("planar_geometry",spec.geometry_features)
        self.assertEqual(spec.product_mask.status,EvidenceStatus.UNKNOWN)

    def test_provider_missing_or_unknown_weight_does_not_download(self):
        with self.assertRaises(FileNotFoundError):BiRefNetLiteProvider(self.root/"missing.onnx")
        unknown=self.root/"other.onnx";unknown.write_bytes(b"not a trusted model")
        with self.assertRaises(ValueError):BiRefNetLiteProvider(unknown)

    def test_cli_invalid_path_and_mandatory_instance_selection(self):
        with redirect_stderr(io.StringIO()),redirect_stdout(io.StringIO()):
            self.assertEqual(main(["segment","missing.png","--single-instance"],project_root=self.root),2)
            with self.assertRaises(SystemExit):main(["segment",str(self.source)],project_root=self.root)

    def test_explicit_point_selection_can_keep_one_or_multiple_parts(self):
        alpha=np.zeros((100,160),np.uint8);alpha[10:50,10:50]=255;alpha[60:90,100:140]=255
        one,record=select_by_points(alpha,[(20,20)])
        self.assertEqual(one[20,20],255);self.assertEqual(one[70,110],0)
        two,_=select_by_points(alpha,[(20,20),(110,70)])
        np.testing.assert_array_equal(two,alpha)
        self.assertEqual(record["mode"],"explicit_positive_point_component_selection")
        with self.assertRaises(ValueError):select_by_points(alpha,[(0,0)])

    def test_non_square_roi_pixel_mapping_is_exact(self):
        local=np.arange(50*90,dtype=np.uint16).reshape(50,90).astype(np.uint8)
        full=place_roi_alpha(local,(20,15,90,50),(160,100))
        np.testing.assert_array_equal(full[15:65,20:110],local)
        self.assertFalse(np.any(full[:15]));self.assertFalse(np.any(full[:,110:]))

    def test_changed_source_or_rgba_cannot_be_approved(self):
        result=self.create()
        rgba=np.asarray(Image.open(self.root/"asset/product_rgba.png")).copy();rgba[30,20,0]=111
        Image.fromarray(rgba).save(self.root/"asset/product_rgba.png")
        with self.assertRaises(ValueError):self.approve(result)
        result=self.create(out="second")
        changed=self.rgb.copy();changed[40,30]=0;Image.fromarray(changed).save(self.source)
        with self.assertRaises(ValueError):self.approve(result,folder="second")

    def test_edited_cached_quality_cannot_approve_empty_alpha(self):
        result=self.create(alpha=np.zeros_like(self.alpha))
        result["quality"]["automatic_status"]="needs_human_review"
        (self.root/"asset/segmentation_result.json").write_text(json.dumps(result),encoding="utf-8")
        with self.assertRaises(ValueError):self.approve(result)

    def test_review_request_reduces_parameters_without_losing_version_binding(self):
        self.create();path=self.root/"asset/mask_review_request.json"
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            code=main(["review","--request-file",str(path),"--reviewer","UNIT_TEST_REVIEWER_NOT_USER"],project_root=self.root)
        self.assertEqual(code,0)
        request=json.loads(path.read_text(encoding="utf-8"));request["expected_version"]="wrong_version"
        path.write_text(json.dumps(request),encoding="utf-8")
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
            self.assertEqual(main(["review","--request-file",str(path),"--reviewer","UNIT_TEST_REVIEWER_NOT_USER"],project_root=self.root),2)

    def test_existing_transparent_input_does_not_reveal_hidden_rgb(self):
        source_alpha=np.full((100,160),255,np.uint8);source_alpha[20:40,10:30]=0
        rgba=np.dstack((self.rgb,source_alpha));Image.fromarray(rgba).save(self.source)
        result=self.create()
        output=np.asarray(Image.open(self.root/"asset/product_rgba.png"))
        self.assertEqual(output[30,20,3],0)
        self.assertEqual(result["provider"]["source_alpha_policy"],"existing_transparency_honored_no_hidden_pixel_recovery")

    def test_rgb_icc_profile_is_preserved_with_pixel_values(self):
        from PIL import ImageCms
        profile=ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        Image.fromarray(self.rgb).save(self.source,icc_profile=profile)
        result=self.create()
        with Image.open(self.root/"asset/product_rgba.png") as opened:
            self.assertEqual(opened.info["icc_profile"],profile)
            np.testing.assert_array_equal(np.asarray(opened)[:,:,:3],self.rgb)
        self.assertEqual(result["rgb_policy"]["icc_profile"],"preserved")


if __name__=="__main__":unittest.main()
