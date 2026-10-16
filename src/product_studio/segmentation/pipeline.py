"""前景资产输出、历史规格复用和只限遮罩的具名审核。"""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image

from product_studio.core.asset_binding import file_sha256,mask_version
from product_studio.core.schemas import Evidence,EvidenceStatus as Status,ProductInstance,ProductSpec,SourceImage
from product_studio.segmentation.mask_processing import (validate_roi,place_roi_alpha,make_rgba,make_previews,import_external_mask,select_by_points)
from product_studio.segmentation.quality import inspect_mask


def read_spec(path,source):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("schema_version")=="1a.1":
        from product_studio.plugins.planar_geometry.analyzer import adapt_legacy_spec
        old_source = raw.get("source_image",{})
        if (old_source.get("width_px"),old_source.get("height_px"))!=(source.width_px,source.height_px) or (old_source.get("sha256") and old_source["sha256"]!=source.sha256):
            raise ValueError("旧格式来源尺寸/哈希不匹配。")
        return adapt_legacy_spec(raw,source,product_id="legacy_import")
    return ProductSpec.from_dict(raw)


def source_alpha_ceiling(path):
    with Image.open(path) as opened:
        if "A" in opened.getbands() or "transparency" in opened.info:
            return np.asarray(opened.convert("RGBA").getchannel("A")).copy()
    return None


def build_context(source_path,roi,instance_id,*,spec_path=None):
    source_path=Path(source_path).resolve()
    with Image.open(source_path) as opened:
        rgb = np.asarray(opened.convert("RGB")).copy()
        orientation = opened.getexif().get(274,1)
    height,width=rgb.shape[:2]
    roi=validate_roi(tuple(roi),width,height)
    digest=file_sha256(source_path)
    source=SourceImage("source_"+digest[:16],str(source_path),digest,width,height)
    spec=read_spec(spec_path,source) if spec_path else ProductSpec("product_"+digest[:16]+"/"+instance_id,[source])
    if spec_path:
        matches=[item for item in spec.source_images if item.sha256==digest and (item.width_px,item.height_px)==(width,height)]
        if len(matches)!=1: raise ValueError("规格必须唯一关联当前输入图，不能借用其他 SKU 来源。")
        source=replace(matches[0],path=str(source_path))
        spec.source_images=[source if item.source_id==source.source_id else item for item in spec.source_images]
        if spec.selected_instance and spec.selected_instance!=instance_id:
            raise ValueError("输入规格选中的实例与请求不一致。")
    prior=next((item for item in spec.detected_instances if item.instance_id==instance_id),None)
    if prior and prior.source_id!=source.source_id: raise ValueError("实例属于另一来源。")
    selected=ProductInstance(instance_id,source.source_id,roi,Evidence(True,Status.ESTIMATED,(source.source_id,),"explicit_roi_selection"),prior.sku if prior else None)
    spec.detected_instances=[item for item in spec.detected_instances if item.instance_id!=instance_id]+[selected]
    spec.selected_instance=instance_id
    return rgb,source,spec,orientation


def export_segmentation(rgb,alpha,raw_alpha,source,spec,roi,output_dir,provider_metadata,*,risks=(),parent=None,orientation=1):
    output_dir=Path(output_dir).resolve()
    if output_dir.exists() and any(output_dir.iterdir()): raise ValueError("输出目录非空，禁止混入旧版本或另一实例。")
    quality=inspect_mask(rgb,alpha,roi,risks=risks)
    if orientation!=1: quality["warnings"].append("EXIF orientation not applied; coordinates are stored-image pixels")
    with Image.open(source.path) as opened:
        source_mode=opened.mode;source_profile=opened.info.get("icc_profile")
    profile=source_profile if source_mode in {"RGB","RGBA"} else None
    if source_profile and profile is None:quality["warnings"].append("non_RGB_ICC_profile_conversion_requires_color_review")
    png_options={"icc_profile":profile} if profile else {}
    output_dir.mkdir(parents=True,exist_ok=True)
    Image.fromarray(alpha).save(output_dir/"alpha_mask.png")
    Image.fromarray(raw_alpha).save(output_dir/"raw_alpha_mask.png")
    rgba=make_rgba(rgb,alpha)
    Image.fromarray(rgba).save(output_dir/"product_rgba.png",**png_options)
    for name,image in make_previews(rgb,alpha).items(): Image.fromarray(image).save(output_dir/name,**png_options)
    snapshot=output_dir/("source_original"+Path(source.path).suffix.lower())
    shutil.copyfile(source.path,snapshot)
    mask_hash=file_sha256(output_dir/"alpha_mask.png")
    version=mask_version(source.source_id,source.sha256,spec.selected_instance,roi,mask_hash)
    rgba_hash=file_sha256(output_dir/"product_rgba.png")
    value={"artifact":str(output_dir/"alpha_mask.png"),"rgba_artifact":str(output_dir/"product_rgba.png"),
           "source_id":source.source_id,"source_sha256":source.sha256,"instance_id":spec.selected_instance,
           "roi":list(roi),"mask_sha256":mask_hash,"mask_version":version,"rgba_sha256":rgba_hash,
           "coordinate_system":"source_pixels","quality":"needs_review"}
    # 修正产生新版本，撤销该实例旧 mask 审核，保留其他属性但不标全商品已审核。
    spec.product_mask=Evidence(value,Status.ESTIMATED,(source.source_id,),provider_metadata["provider"],note="模型/修正结果待人工检查。")
    spec.verified_facts.pop("product_mask",None)
    spec.human_review_status="pending" if not spec.verified_facts else "partially_reviewed"
    spec.analysis_records.append({"analyzer":"segmentation","status":quality["automatic_status"],"mask_version":version})
    spec.warnings.append("Alpha 是分割估计，玻璃物理透射、内壁与背景污染须审核；RGB未重绘。")
    (output_dir/"product_spec.json").write_text(spec.to_json(),encoding="utf-8")
    request={"schema_version":"mask_review_request.2a.1","result":str(output_dir/"segmentation_result.json"),
             "expected_source_id":source.source_id,"expected_instance_id":spec.selected_instance,"expected_version":version,
             "scope":"mask_only","approved":False}
    (output_dir/"mask_review_request.json").write_text(json.dumps(request,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    result={"schema_version":"segmentation.2a.1","status":quality["automatic_status"],
            "source":{"source_id":source.source_id,"path":source.path,"sha256":source.sha256,
                      "width_px":source.width_px,"height_px":source.height_px,"snapshot":snapshot.name},
            "instance_id":spec.selected_instance,"roi":list(roi),"coordinate_system":"source_pixels",
            "output_size_px":[source.width_px,source.height_px],"binding":value,
            "provider":provider_metadata,"quality":quality,"human_review":{"status":"pending","reviewer":None},
            "rgb_policy":{"original_decoded_rgb_preserved":bool(np.array_equal(rgba[:,:,:3],rgb)),
                          "decontamination":"not_applied","repainting":False,"outside_roi_alpha":0,
                          "input_mode":source_mode,"icc_profile":"preserved" if profile else ("absent" if not source_profile else "unsupported_non_RGB_profile")},
            "processing":["ROI selected explicitly","soft Alpha mapped to source pixels","no color-based erasure; no hole filling",
                          "all regions retained unless explicit component points or an external corrected mask were supplied"],
            "parent_result":parent,"created_at_utc":datetime.now(timezone.utc).isoformat(),
            "artifacts":{p.name:file_sha256(p) for p in output_dir.iterdir() if p.is_file()}}
    (output_dir/"segmentation_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def segment(source_path,roi,instance_id,output_dir,provider,*,spec_path=None,risks=(),keep_points=()):
    rgb,source,spec,orientation=build_context(source_path,roi,instance_id,spec_path=spec_path)
    x,y,w,h=roi
    prediction=provider.predict(rgb[y:y+h,x:x+w])
    raw=place_roi_alpha(prediction.alpha,roi,(source.width_px,source.height_px))
    ceiling=source_alpha_ceiling(source_path)
    visible=raw if ceiling is None else np.minimum(raw,ceiling)
    alpha,selection=select_by_points(visible,list(keep_points))
    return export_segmentation(rgb,alpha,raw,source,spec,roi,output_dir,{**prediction.metadata,"instance_selection":selection,
                               "source_alpha_policy":"opaque_source" if ceiling is None else "existing_transparency_honored_no_hidden_pixel_recovery"},risks=risks,orientation=orientation)


def load_result(path):
    path=Path(path).resolve()
    result=json.loads(path.read_text(encoding="utf-8"))
    if result.get("schema_version")!="segmentation.2a.1": raise ValueError("不支持的分割记录版本。")
    binding=result["binding"]
    for key,value in (("source_id",result["source"]["source_id"]),("source_sha256",result["source"]["sha256"]),("instance_id",result["instance_id"]),("roi",result["roi"])):
        if binding.get(key)!=value: raise ValueError("分割记录来源/实例绑定被改变。")
    actual=file_sha256(path.parent/"alpha_mask.png")
    if actual!=binding["mask_sha256"] or binding["mask_version"]!=mask_version(binding["source_id"],binding["source_sha256"],binding["instance_id"],binding["roi"],actual):
        raise ValueError("遮罩文件已修改或版本不匹配；请导入为新版本，不可沿用旧审核。")
    return path,result


def correct_mask(result_path,mask_path,coordinates,output_dir):
    path,prior=load_result(result_path)
    rgb,source,spec,orientation=build_context(prior["source"]["path"],tuple(prior["roi"]),prior["instance_id"],spec_path=path.parent/"product_spec.json")
    if source.sha256!=prior["source"]["sha256"]: raise ValueError("原图已修改，拒绝用旧 mask 绑定新来源。")
    alpha=import_external_mask(Path(mask_path),coordinates=coordinates,roi=tuple(prior["roi"]),source_size=(source.width_px,source.height_px))
    ceiling=source_alpha_ceiling(prior["source"]["path"])
    if ceiling is not None and np.any(alpha>ceiling):raise ValueError("修正 mask 将恢复原输入透明区域的隐藏像素，需要提供真实 RGB 原图，不能猜测。")
    metadata={"provider":"external_mask_import","mask_path":str(Path(mask_path).resolve()),"mask_file_sha256":file_sha256(mask_path),
              "input_coordinates":coordinates,"automatic_model_executed":False,"original_provider":prior["provider"]}
    with Image.open(path.parent/"raw_alpha_mask.png") as opened: raw=np.asarray(opened.convert("L")).copy()
    result=export_segmentation(rgb,alpha,raw,source,spec,tuple(prior["roi"]),output_dir,metadata,parent=str(path),orientation=orientation)
    snapshot_name="correction_input"+Path(mask_path).suffix.lower()
    snapshot=Path(output_dir)/snapshot_name
    shutil.copyfile(mask_path,snapshot)
    result["artifacts"][snapshot_name]=file_sha256(snapshot)
    result["provider"]["correction_snapshot"]=snapshot_name
    (Path(output_dir)/"segmentation_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return result


def review_mask(result_path,*,reviewer,expected_source_id,expected_instance_id,expected_version):
    if not isinstance(reviewer,str) or not reviewer.strip(): raise ValueError("审核人必须具名。")
    path,result=load_result(result_path)
    binding=result["binding"]
    if (expected_source_id,expected_instance_id,expected_version)!=(binding["source_id"],binding["instance_id"],binding["mask_version"]):
        raise ValueError("审核请求的来源、实例或 mask 版本不匹配。")
    if result["quality"]["automatic_status"]=="failed": raise ValueError("空遮罩或跨 ROI 遮罩不能确认为完整。")
    if file_sha256(result["source"]["path"])!=binding["source_sha256"]: raise ValueError("来源已修改。")
    with Image.open(result["source"]["path"]) as opened:
        original=np.asarray(opened.convert("RGB"));original_profile=opened.info.get("icc_profile");original_mode=opened.mode
    with Image.open(path.parent/"product_rgba.png") as opened:
        rgba=np.asarray(opened.convert("RGBA"));rgba_profile=opened.info.get("icc_profile")
    if original_profile and (original_mode not in {"RGB","RGBA"} or original_profile!=rgba_profile):raise ValueError("来源色彩配置文件未正确保留，需先处理颜色风险再审核。")
    with Image.open(path.parent/"alpha_mask.png") as opened: alpha=np.asarray(opened.convert("L"))
    if not np.array_equal(rgba[:,:,:3],original) or not np.array_equal(rgba[:,:,3],alpha) or file_sha256(path.parent/"product_rgba.png")!=binding["rgba_sha256"]:
        raise ValueError("RGBA 与来源/Alpha/资产哈希不一致，不能审核。")
    spec=ProductSpec.from_dict(json.loads((path.parent/"product_spec.json").read_text(encoding="utf-8")))
    selected=next(item for item in spec.detected_instances if item.instance_id==spec.selected_instance)
    if selected.instance_id!=binding["instance_id"] or selected.source_id!=binding["source_id"] or list(selected.roi)!=binding["roi"]:
        raise ValueError("product_spec 实例与待审核版本不匹配。")
    source=next(item for item in spec.source_images if item.source_id==selected.source_id)
    if source.sha256!=binding["source_sha256"] or alpha.shape!=(source.height_px,source.width_px):raise ValueError("规格来源版本/尺寸与遮罩不匹配。")
    if inspect_mask(original,alpha,tuple(binding["roi"]))["automatic_status"]=="failed":raise ValueError("实时检查发现空遮罩或跨 ROI 前景，拒绝审核。")
    record={**binding,"reviewer":reviewer.strip(),"approved":True,"scope":"mask_only",
            "reviewed_at_utc":datetime.now(timezone.utc).isoformat()}
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    record_path=path.parent/f"mask_review_{stamp}.json"
    record_path.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    value={**binding,"quality":"reviewed_complete","review_record":str(record_path)}
    fact=Evidence(value,Status.HUMAN_VERIFIED,(binding["source_id"],),"explicit_mask_review",reviewer=reviewer.strip(),note="仅审核该来源/实例/文件版本的遮罩，不确认几何或隐藏结构。")
    spec.product_mask=fact;spec.verified_facts["product_mask"]=fact;spec.human_review_status="partially_reviewed"
    (path.parent/"product_spec.json").write_text(spec.to_json(),encoding="utf-8")
    result["binding"]=value;result["human_review"]={"status":"mask_approved","reviewer":reviewer.strip(),"scope":"mask_only","mask_version":binding["mask_version"]}
    result["artifacts"]={item.name:file_sha256(item) for item in path.parent.iterdir() if item.is_file() and item.name!="segmentation_result.json"}
    (path.parent/"segmentation_result.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    return record
