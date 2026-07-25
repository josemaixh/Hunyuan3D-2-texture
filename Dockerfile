FROM nvidia/cuda:12.4.1-devel-ubuntu22.04

# --- Internal testing/prototyping build only ---

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    CUDA_HOME=/usr/local/cuda

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
RUN cd hy3dgen/texgen/differentiable_renderer && bash compile_mesh_painter.sh

# RunPod worker SDK + B2 (S3-compatible) client + mesh loading
RUN pip install --no-cache-dir runpod boto3 trimesh pillow

# Bake the Hunyuan3D-2 texgen weights into the image so workers don't
# download them on cold start
RUN python -c "from hy3dgen.texgen import Hunyuan3DPaintPipeline; Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2')"

# RunPod handler
COPY handler.py /workspace/Hunyuan3D-2/handler.py

CMD ["python", "-u", "handler.py"]
