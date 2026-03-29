FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install Python dependencies used by API service
COPY scripts/etl/requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip && pip install -r /tmp/requirements.txt

# Copy backend source and schema artifacts
COPY scripts/ scripts/
COPY db/ db/

EXPOSE 8000

CMD ["uvicorn", "scripts.main:app", "--host", "0.0.0.0", "--port", "8000"]
