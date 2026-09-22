FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

# Install system dependencies for psycopg2, Pillow, and kagglehub
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (core deps first, torch comes from base image)
COPY detector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy detection package
COPY detection/ /app/detection/

# Copy detector package
COPY detector/ /app/detector/

# Copy config
COPY config/ /app/config/

CMD ["python", "-m", "detector.main"]
