FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.12-slim AS runtime

WORKDIR /app

# Install runtime shared C-libraries required by Docling, PyMuPDF, OpenCV and OCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH
ENV PYTHONPATH=/root/.local/lib/python3.12/site-packages

# Fetch Docling's PDF models (layout, table structure, OCR) once, here, so the first upload
# does not download them (QA-026). This runs in the runtime stage, not the builder, because
# importing Docling needs the shared libraries installed above (OpenCV wants libGL; in the
# builder the import fails with "libGL.so.1: cannot open shared object file"). The
# DOCLING_ARTIFACTS_PATH set after it makes Docling load the models from this directory. The
# build needs internet access to huggingface.co; if this step fails, run the build again.
RUN python -c "from pathlib import Path; from docling.utils.model_downloader import download_models; download_models(Path('/opt/docling-models'), with_code_formula=False, with_picture_classifier=False)"
ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
