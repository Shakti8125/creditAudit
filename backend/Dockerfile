FROM python:3.13-slim as builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.13-slim as runtime

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
ENV PYTHONPATH=/root/.local/lib/python3.13/site-packages:$PYTHONPATH

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
