FROM python:3.11-slim

# Install system dependencies & Stockfish binary
RUN apt-get update && apt-get install -y --no-install-recommends \
    stockfish \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application source
COPY . .

# Environment defaults
ENV PYTHONUNBUFFERED=1
ENV STOCKFISH_PATH=/usr/games/stockfish

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
