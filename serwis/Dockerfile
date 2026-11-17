FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HF_HOME=/opt/hf
WORKDIR /srv

# OCR skanów: OCRmyPDF z Tesseractem i modelem polskim, poppler do sprawdzania warstwy tekstowej PDF
RUN apt-get update && apt-get install -y --no-install-recommends ocrmypdf tesseract-ocr-pol poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# PyTorch w wersji CPU (osobny indeks, żeby nie ciągnąć bibliotek CUDA)
RUN pip install --no-cache-dir torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Model NER pobierany przy budowie obrazu. W trakcie pracy kontener nie sięga do internetu po modele.
ARG HF_NER_MODEL=clarin-pl/FastPDN
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('${HF_NER_MODEL}')"
# Modele EasyOCR (detektor i rozpoznawanie alfabetu łacińskiego z polskimi znakami), także pobierane przy budowie
ENV EASYOCR_MODULE_PATH=/opt/easyocr
RUN python -c "import easyocr; easyocr.Reader(['pl'], gpu=False)"
ENV HF_NER_MODEL=${HF_NER_MODEL} HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

COPY app ./app
COPY testy ./testy

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
