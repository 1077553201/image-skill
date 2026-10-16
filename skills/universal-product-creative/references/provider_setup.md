# External services

Explicit COMFYUI_BASE_URL enables backgrounds. Bundled graph is an actual successful QwenImage 2.1 API graph, not an editor. Missing server nodes/models raise errors; no Conda environment is altered.

For another graph: config-dir/comfyui.json has base_url, workflow_path relative to config file, workflow_source.original_sha256, mapping positive/negative/width/height/seed/prefix each with node/input/class_type, output_node and timeouts. Use real exported API JSON and verified node mappings. Never invent connections/models.

PRODUCT_STUDIO_SEGMENTATION_MODEL explicitly points at supported ONNX weight; no weights bundled. Fonts must be installed/licensed locally. Credentials stay in environment or external config.


Optional actual image edit: product-studio-image-edit --config <skill>/configs/image_edit.example.json --image <photo> --prompt <instruction> --seed <integer> --output <new-dir> --truth-mode concept_creative. Set COMFYUI_BASE_URL explicitly. The shipped edit graph is derived from a real successful single-reference Qwen 2.1 run, with source hashes/mappings; your server still needs the corresponding actual nodes/models. This is a separate capability, image_guided_creative_edit, not background_only. Strict_product is rejected before upload/submission. Generated product pixels/texture/hardware may change, all results remain concept/pending. Multi-reference, mask control, wearing/holding and hard identity consistency are not validated by this MVP.
