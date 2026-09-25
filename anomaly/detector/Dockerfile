FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

WORKDIR /app

# Install system dependencies for psycopg2, Pillow, and the cv2 wheel
# (opencv-python-headless still links glib)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libglib2.0-0 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies (core deps first, torch comes from base image)
COPY detector/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy detection package
COPY detection/ /app/detection/

# Copy detector package
COPY detector/ /app/detector/

# No config is baked in: the stack reads the session's own config, which the
# `config-sync` sidecar downloads into the /app/config volume before this
# container starts (see docker-compose.yml).

CMD ["python", "-m", "detector.main"]
