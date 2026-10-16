# Design artifacts and commands

Explicit inputs only. The engine does not infer a checkout or SKU from filenames. Agent-authored design data is not human-verified product evidence.

```text
product-studio design --session <dir> init --binding <binding.json>
product-studio design --session <dir> put --kind creative_brief --file <brief.json>
product-studio design --session <dir> put --kind product_analysis --file <product.json>
product-studio design --session <dir> put --kind reference_analysis --file <references.json>
product-studio design --session <dir> put --kind creative_concepts --file <concepts.json>
product-studio design --session <dir> approve-concept --id <id> --reviewer <user> --statement <actual-answer>
product-studio design --session <dir> put --kind page_designs --file <pages.json>
product-studio design --session <dir> status
```

After actual page approval only:

```text
product-studio design --session <dir> approve-page --id <id> --reviewer <user> --statement <actual-approval>
product-studio design --session <dir> handoff --id <id> --result <segmentation_result.json>
```

handoff returns a checked design/background prompt and provider_submitted:false; never generation. Missing/stale page approval blocks it. Skill run_campaign.py takes these same arguments after design, including --session.

Binding: source_id, source_sha256, instance_id, roi, mask_version, mask_sha256, rgba_sha256. New source/version requires re-planning in a new session. Never replace pointers to inherit approvals.

Creative Brief separates user_requirements, verified_product_facts, visual_observations, design_recommendations, unknown_properties, blocking_questions. Missing facts remain null/unknown. Ask only genuinely blocking questions; optional publishing details can wait.

Product analysis records actual image-read tool, binding, visible view, observations, risks and protected features. Reuse the fact resolver. Reference analysis records real assets/principles or status:not_provided with assets:[]. Concepts contain 2–3 unique concept_id values and complete distinct proposals.

Page packet: {concept_id, pages:[PageDesign,...]}. Required PageDesign fields: page_id, page_purpose, key_message, target_audience, consumer_copy (headline/body/eyebrow), composition (normalized xywh text_regions), product_position (normalized center), product_scale (display region longest-edge fraction), camera_angle, focal_point, background_description, lighting_design, color_palette, typography, decorative_elements, layer_structure, required_assets, image_generation_route, output_size, fidelity_level, quality_criteria.

Layers ordered by z. Sketch kinds: background; graphic(rect/color); source_foreground(rect); source_crop(rect/crop_xywh); type(rect/copy_key/size/color). Rects normalized xywh, crops source pixels. Coordinates are individual design data, not family defaults. Actual product editing is not executable through this handoff.

Each mutation exclusively creates revisions/<number>.json containing a full snapshot, event and parent SHA256. session.json points to the current snapshot/hash. Approval binds context/page hashes. Revised pages lose only their own approvals. This is single-writer local audit/tamper detection, not user authentication or a concurrent database. Quote actual answers and name the actual respondent; never impersonate a reviewer. Final assets remain pending.
