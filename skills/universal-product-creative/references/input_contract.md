> Legacy backend reference. Start with design_workflow.md; this contract does not authorize generation before page approval.

# Request and visual handoff

Minimal request:
```json
{"product_id":"current_item","product_asset":"asset/asset_bundle.json","output_count":6,"language":"en"}
```

Alternatively product_image plus instance_selection (single_instance:true or roi:[x,y,w,h]) needs explicit segmentation weight and optional dependency. Inputs are exclusive. Optional: product_facts, reference_url/reference_images, style_preference, platform, generation_budget.max_new_backgrounds, review_policy.mode auto/strict/preview. No implicit sample paths.

After --prepare inspect source and handoff. Agent JSON uses schema_version product_understanding.4b.1, provider image_capable_agent, actual image_read_tool, exact handoff binding, display_name, visible_view, facts, fact_kinds, features, detail_regions, recommended_intents, copy, style, risks. Facts have value/status observed or unknown/sources [current source_id]/method. Unknown value=null. Agent cannot human-verify. User facts need actual statement, reviewer and current product_id provenance.

Features and copy refer to grounded fact_ids. Real detail_regions use source-pixel bbox [x,y,w,h], label and fact_ids. Supported intents: white_hero, studio_photo, feature_infographic, material_detail, structure_explainer, specifications, comparison, brand_signature, editorial_campaign, lifestyle_scene, wide_banner. Evidence gates skip unavailable intents.

copy maps each intent to headline/body/fact_ids. style includes name, palette, fonts and background_briefs.studio/environment with prompt/negative. Do not invent unobserved performance. References require engine fourteen-dimension image-hash-bound analysis. Without references use original direction, not a fictional reference analysis.

Identifiers: product_id is a campaign-safe ID matching [A-Za-z0-9][A-Za-z0-9_-]{0,79}, not the slash-containing canonical product_spec ID. platform is generic/amazon/ebay/social, not free text; buyer/channel context belongs in audience/creative notes. English/Chinese use language en/zh. Palette is a dictionary of hex RGB colors with keys paper, white, ink, muted, navy, blue, cyan, line; absent keys get neutral defaults. Do not copy file paths from another asset binding.


Engine 0.3 extension: use consumer_copy (intent -> headline/body/fact_ids), internal_notes, provenance as separate objects. Legacy copy is an input adapter; internal_notes are never substituted. task_intent is product_marketing. Only a separate production_disclosure object with allow_production_disclosure:true and actual user_statement can authorize production-language captions.

The handoff includes current_product_facts/confirmed_fact_ids and selected_instance_preview. Treat inherited human confirmations as authoritative for this exact asset; never recreate an already resolved question from scratch. Conflicts are errors. The engine reads these through resolve_product_facts, without a cross-SKU global fact store.

creative_direction can specify enabled, product_use, target_buyer, campaign_goal, reference_language, mood, photography_scene, information_density, sequence_rationale, and intent_layouts mapping each intent to family/reason. Installed generation enables the current director by default. Available families: full_frame, asymmetric_editorial, typographic_poster, minimal_negative_space, magazine_cover, macro_story, technical_grid, wide_atmosphere. Macro needs an actual source crop. Choose useful families for the purpose; category does not select a fixed family. Scene level 1 supports non-contact atmosphere, preserving the source view without a white presentation panel. Legacy level 2 panels remain compatible.

Generation budget counts only NEW submissions; max_new_backgrounds=0 can render an explicit matching successful cache. A different prompt/background needs a new version and budget, not falsified cache provenance.
