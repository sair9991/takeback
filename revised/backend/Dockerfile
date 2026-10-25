FROM python:3.11-slim

# Install system dependencies & Stockfish binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    stockfish \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements (using PyTorch CPU wheel to avoid heavy NVIDIA CUDA downloads)
COPY requirements.txt .
RUN pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt

# Copy backend application source
COPY . .

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV STOCKFISH_PATH=/usr/games/stockfish

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
