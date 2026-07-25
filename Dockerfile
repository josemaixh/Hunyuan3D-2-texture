FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

WORKDIR /workspace

# System deps needed to build custom_rasterizer / differentiable_renderer
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    wget \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Clone Hunyuan3D-2 (we only need the texgen half, but the repo ships as one package)
RUN git clone --depth 1 https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git /workspace/Hunyuan3D-2

WORKDIR /workspace/Hunyuan3D-2

# Core python deps
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -e .

# Build the texgen native extensions (custom_rasterizer + differentiable renderer)
RUN cd hy3dgen/texgen/custom_rasterizer && python3 setup.py install
RUN cd hy3dgen/texgen/differentiable_renderer && bash compile_mesh_painter.sh

# RunPod serverless SDK + our handler deps
RUN pip install --no-cache-dir runpod trimesh b2sdk pillow

# Pre-download the Hunyuan3D-2 texgen weights at build time so cold starts don't
# have to hit the HF hub (mirrors what we did for the Trellis image)
RUN python3 -c "from hy3dgen.texgen import Hunyuan3DPaintPipeline; Hunyuan3DPaintPipeline.from_pretrained('tencent/Hunyuan3D-2')"

WORKDIR /workspace
COPY handler.py /workspace/handler.py

CMD ["python3", "-u", "handler.py"]
