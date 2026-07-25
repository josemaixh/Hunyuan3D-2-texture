# Hunyuan3D-Paint texture-only RunPod image

Retextures an existing mesh (e.g. your TRELLIS.2 GLB output) using Hunyuan3D-2's
paint stage only — shape generation is skipped entirely.

## What's in here
- `Dockerfile` — clones Hunyuan3D-2, builds the texgen native extensions
  (`custom_rasterizer`, `differentiable_renderer`), pre-downloads the paint
  model weights at build time so cold starts are fast.
- `handler.py` — RunPod Serverless handler. Takes a mesh URL + reference image
  URL, runs `Hunyuan3DPaintPipeline`, uploads the result to B2, returns the URL.

## GPU sizing
Hunyuan3D-Paint needs meaningfully more VRAM than you might expect — the 2.1
docs cite ~21GB for the paint pipeline alone. Use at least a 24GB card
(RTX 3090/4090 or A5000) on the RunPod endpoint config. If you hit OOM, drop
texture resolution via `_pipeline.set_resolution(...)` before calling it (add
that call to `handler.py` if needed).

## Build & push (mirrors your Trellis GitHub Actions flow)

```bash
docker build -t <your-dockerhub-user>/hunyuan3d-texgen:latest .
docker push <your-dockerhub-user>/hunyuan3d-texgen:latest
```

If you want this in GitHub Actions like the Trellis pipeline, the job is the
same shape: build on push to main, tag with the commit SHA, push to your
registry, then update the RunPod endpoint to the new image tag.

## RunPod endpoint setup
1. Create a new Serverless endpoint pointing at the pushed image.
2. Set container env vars: `B2_KEY_ID`, `B2_APPLICATION_KEY`, `B2_BUCKET_NAME`
   (same values as your Trellis endpoint, assuming you're using the same bucket).
3. GPU: 24GB+ tier.
4. Container disk: give it enough headroom for the pre-baked model weights
   (Hunyuan3D-2 texgen weights are a few GB) — 20GB+ recommended.

## Test call (files already hosted, e.g. in B2)

```bash
curl -X POST https://api.runpod.ai/v2/<endpoint-id>/runsync \
  -H "Authorization: Bearer <runpod-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "input": {
      "mesh_url": "https://<your-b2-bucket>/trellis_dish123.glb",
      "image_url": "https://<your-b2-bucket>/dish123_reference.jpg"
    }
  }'
```

## Test call with local files (no B2 upload needed)

Use `test_local.py` to send your Trellis GLB and reference photo straight
from your PC as base64 — good for the quick A/B test before you commit to
wiring this into the full pipeline.

```bash
export RUNPOD_ENDPOINT_ID=<your-endpoint-id>
export RUNPOD_API_KEY=<your-runpod-api-key>

python test_local.py ./trellis_dish123.glb ./dish123_reference.jpg
```

It base64-encodes both files, submits the job, polls until it completes, and
prints the resulting GLB's B2 URL (the handler still uploads the *output* to
B2 — only the inputs skip that step).

**Payload size caveat:** RunPod's `/run` endpoint has a request size limit
(historically ~10MB for the job input). Most reference photos are fine, but
if a Trellis GLB is large (dense mesh + textures), base64 can push it over
that limit and the request will get rejected before it even reaches the
handler. If you hit that, the fallback is to upload the mesh to B2 first
(quick script, or just drag it into your bucket) and pass `mesh_url` instead,
while keeping `image_base64` for the photo since images are usually small.

Expected response either way:
```json
{ "output": { "glb_url": "https://<bucket>/<uuid>.glb" } }
```

Pull that URL into your local model-viewer / ngrok AR test setup the same way
you've been checking the Trellis outputs, and compare texture quality side by
side with the original Trellis GLB.

## Notes / known friction points
- The `custom_rasterizer` and `differentiable_renderer` builds are the most
  common failure point in community reports — if the Docker build fails there,
  check the build logs first before touching anything else.
- `trimesh.load(..., force="mesh")` is used to make sure we get a single mesh
  object regardless of how the Trellis GLB is structured (some exporters wrap
  it in a Scene with one geometry). If your Trellis GLBs are multi-mesh
  scenes, this will need adjusting to merge or select the right geometry.
