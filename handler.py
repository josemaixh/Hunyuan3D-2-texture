"""
RunPod Serverless handler for texture-only regeneration using Hunyuan3D-Paint.

Input job payload -- either URL-based or base64 upload-based (mix and match
per field is fine, e.g. mesh via URL + image via base64):
{
    "input": {
        "mesh_url": "https://.../dish123.glb",        # OR
        "mesh_base64": "<base64 glb bytes>",

        "image_url": "https://.../dish123_ref.jpg",   # OR
        "image_base64": "<base64 image bytes>",
        "image_ext": ".jpg",                          # only needed with image_base64

        "output_key": "dish123_hunyuan_texture.glb"    # optional, defaults to a uuid
    }
}

Output:
{
    "output": {
        "glb_url": "https://<b2-bucket-public-url>/dish123_hunyuan_texture.glb"
    }
}
"""

import os
import uuid
import base64
import tempfile
import requests
import trimesh
import runpod
from hy3dgen.texgen import Hunyuan3DPaintPipeline
from b2sdk.v2 import InMemoryAccountInfo, B2Api

# ---- B2 config (same pattern as the Trellis pod) ----
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APP_KEY = os.environ["B2_APPLICATION_KEY"]
B2_BUCKET_NAME = os.environ["B2_BUCKET_NAME"]

_b2_api = B2Api(InMemoryAccountInfo())
_b2_api.authorize_account("production", B2_KEY_ID, B2_APP_KEY)
_bucket = _b2_api.get_bucket_by_name(B2_BUCKET_NAME)

print("Loading Hunyuan3D-Paint pipeline...")
_pipeline = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
print("Pipeline loaded.")


def _download(url: str, suffix: str) -> str:
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(resp.content)
    return path


def _write_base64(b64_data: str, suffix: str) -> str:
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(base64.b64decode(b64_data))
    return path


def _resolve_input_file(job_input: dict, prefix: str, default_ext: str) -> str:
    """Resolve a mesh/image input that may arrive as a URL or base64 payload."""
    url_key = f"{prefix}_url"
    b64_key = f"{prefix}_base64"

    if job_input.get(b64_key):
        ext = job_input.get(f"{prefix}_ext", default_ext)
        return _write_base64(job_input[b64_key], ext)

    if job_input.get(url_key):
        url = job_input[url_key]
        ext = os.path.splitext(url)[1] or default_ext
        return _download(url, ext)

    raise ValueError(f"Missing input: provide either '{url_key}' or '{b64_key}'")


def handler(job):
    job_input = job["input"]
    output_key = job_input.get("output_key", f"{uuid.uuid4()}.glb")

    mesh_path = _resolve_input_file(job_input, "mesh", ".glb")
    image_path = _resolve_input_file(job_input, "image", ".jpg")

    try:
        mesh = trimesh.load(mesh_path, force="mesh")

        # Skip shape generation entirely -- feed our existing (Trellis) mesh
        # straight into the paint stage along with the reference photo.
        textured_mesh = _pipeline(mesh, image=image_path)

        out_path = os.path.join(tempfile.gettempdir(), output_key)
        textured_mesh.export(out_path)

        uploaded_file = _bucket.upload_local_file(
            local_file=out_path,
            file_name=output_key,
        )
        download_url = _b2_api.get_download_url_for_file_name(
            B2_BUCKET_NAME, uploaded_file.file_name
        )

        return {"glb_url": download_url}

    except Exception as e:
        return {"error": str(e)}

    finally:
        for p in (mesh_path, image_path):
            if os.path.exists(p):
                os.remove(p)


runpod.serverless.start({"handler": handler})
