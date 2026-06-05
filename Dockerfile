#  SPAERO ELT Pipeline Image
#  Runs: extract_load.py → transform.py → inspect_views.py

FROM python:3.11-slim

# System dependencies for psycopg2
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies first (layer cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy pipeline scripts from the scripts/ subfolder
COPY scripts/extract_load.py  .
COPY scripts/transform.py     .
COPY scripts/inspect_views.py .

# Run all three steps in order; stops immediately if any step fails
CMD ["sh", "-c", "python extract_load.py && python transform.py && python inspect_views.py"]