# Install Universal Product Creative

Python >=3.11. Unzip this entire release; copying SKILL.md alone does not install the engine.

```text
python scripts/install_engine.py --venv /your/empty/engine-venv
<engine-python> scripts/preflight.py --output preflight.json
<engine-python> scripts/run_campaign.py --request /your/campaign.json --output /your/outputs
```

Register this folder through the Agent's normal skill mechanism and configure that venv Python. Wheel dependencies are NumPy, Pillow and OpenCV headless. Installation may need package-index access; offline deployment requires their compatible wheels beforehand. No fonts, weights or credentials are redistributed.

Existing assets: product-studio export-asset --result /explicit/segmentation_result.json --output /new/asset. Copy that entire asset directory. Import preserves source/mask/RGBA and immutable review hashes, without granting approvals. Raw photos optionally need the segmentation extra and explicit PRODUCT_STUDIO_SEGMENTATION_MODEL.

AI backgrounds require COMFYUI_BASE_URL. The bundled actual QwenImage API graph requires corresponding nodes/models on that server. For another graph supply --config-dir with comfyui.json and actual API graph. No development service address is silently inherited.

English uses installed Arial/DejaVu. Other languages need explicit licensed local font paths in style_preference.font_regular/font_bold. Relative request paths resolve against the request file; --output resolves against invoking cwd.
