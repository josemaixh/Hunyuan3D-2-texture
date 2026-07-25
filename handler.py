import os
import tempfile
import uuid

import boto3
import requests
import trimesh
import runpod

from hy3dgen.texgen import Hunyuan3DPaintPipeline

# Backblaze B2 (S3-compatible) — same bucket/credentials pattern as the
# Trellis worker. Configure via environment variables.
B2_ENDPOINT_URL = os.environ.get("B2_ENDPOINT_URL", "https://s3.us-east-005.backblazeb2.com")
B2_BUCKET_NAME = os.environ["B2_BUCKET_NAME"]
B2_KEY_ID = os.environ["B2_KEY_ID"]
B2_APPLICATION_KEY = os.environ["B2_APPLICATION_KEY"]

s3_client = boto3.client(
    "s3",
    endpoint_url=B2_ENDPOINT_URL,
    aws_access_key_id=B2_KEY_ID,
    aws_secret_access_key=B2_APPLICATION_KEY,
)

# Loaded once per worker at cold start, reused across warm requests
print("Loading Hunyuan3D-Paint pipeline...")
pipeline = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2")
print("Pipeline ready.")


def _download_to_tempfile(url, suffix):
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    fd, path = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "wb") as f:
        f.write(resp.content)
    return path


def handler(job):
    """
    Expected input:
    {
        "input": {
            "mesh_url": "https://.../trellis_dish123.glb",
            "image_url": "https://.../dish123_reference.jpg"
        }
    }

    Returns:
        { "glb_key": "<B2 object key, e.g. 'models/<uuid>.glb'>" }
    or
        { "error": "<message>" }
    """
    job_input = job.get("input", {})
    mesh_url = job_input.get("mesh_url")
    image_url = job_input.get("image_url")

    if not mesh_url:
        return {"error": "Missing 'mesh_url' in input."}
    if not image_url:
        return {"error": "Missing 'image_url' in input."}

    try:
        mesh_ext = os.path.splitext(mesh_url.split("?")[0])[1] or ".glb"
        image_ext = os.path.splitext(image_url.split("?")[0])[1] or ".jpg"
        mesh_path = _download_to_tempfile(mesh_url, mesh_ext)
        image_path = _download_to_tempfile(image_url, image_ext)
    except Exception as e:
        return {"error": f"Could not download mesh or image: {e}"}

    try:
        mesh = trimesh.load(mesh_path, force="mesh")

        # Skip shape generation entirely -- paint the mesh we already have
        textured_mesh = pipeline(mesh, image=image_path)

        with tempfile.NamedTemporaryFile(suffix=".glb", delete=True) as tmp:
            textured_mesh.export(tmp.name)
            tmp.seek(0)
            glb_bytes = tmp.read()

        # Upload to B2, return the object key (same pattern as the Trellis
        # worker) so Vexly's backend can look it up without depending on a
        # specific URL format.
        object_key = f"models/{uuid.uuid4()}.glb"
        s3_client.put_object(
            Bucket=B2_BUCKET_NAME,
            Key=object_key,
            Body=glb_bytes,
            ContentType="model/gltf-binary",
        )

        return {"glb_key": object_key}

    except Exception as e:
        return {"error": f"Texture generation failed: {e}"}

    finally:
        for p in (mesh_path, image_path):
            if os.path.exists(p):
                os.remove(p)


runpod.serverless.start({"handler": handler})
