FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

# --- Internal testing/prototyping build only ---

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda \
    TORCH_CUDA_ARCH_LIST="8.0;8.6;8.9;9.0"

# System dependencies, incl. what custom_rasterizer / differentiable_renderer need to compile
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.10 python3.10-dev python3-pip \
    git wget ninja-build build-essential libjpeg-dev libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/bin/python \
    && ln -sf /usr/bin/pip3 /usr/bin/pip

# PyTorch (CUDA 12.4)
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 \
    --index-url https://download.pytorch.org/whl/cu124

# Clone Hunyuan3D-2 -- we only need the texgen (Hunyuan3D-Paint) half, but it
# ships as part of the single repo/package
WORKDIR /workspace
RUN git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git
WORKDIR /workspace/Hunyuan3D-2

RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .

# Build the texgen native extensions
RUN cd hy3dgen/texgen/custom_rasterizer && python3 setup.py install
RUN cd hy3dgen/texgen/differentiable_renderer && python3 setup.py install

# RunPod worker SDK + B2 (S3-compatible) client + mesh loading
RUN pip install --no-cache-dir runpod boto3 trimesh pillow

# Bake ONLY the texture-related weights into the image -- skip the
# shape-generation (hunyuan3d-dit-v2-0) weights entirely, since we never use
# them. This keeps the image small enough to build on GitHub's runner.
# Uses snapshot_download (file download only, no GPU touch) rather than
# instantiating the pipeline.
RUN pip install --no-cache-dir huggingface_hub && \
    python -c "\
from huggingface_hub import snapshot_download; \
snapshot_download('tencent/Hunyuan3D-2', allow_patterns=['hunyuan3d-delight-v2-0/*', 'hunyuan3d-paint-v2-0/*'])"

# RunPod handler
COPY handler.py /workspace/Hunyuan3D-2/handler.py

CMD ["python", "-u", "handler.py"]
