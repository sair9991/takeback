# Revised Backend & Database Architecture

This directory contains the containerized, production-ready backend and PostgreSQL database setup for the Chess Clone & Analysis Engine.

---

## Architecture Overview

* **Database (`db`)**: PostgreSQL 16 Alpine with initialized schema (`init.sql`), composite indexing for pagination, and persistent Docker volume storage.
* **LLM Engine (`gemma`)**: `ghcr.io/ggerganov/llama.cpp:server` running quantized Gemma 2 2B (`gemma-2-2b-it-Q4_K_M.gguf`) on CPU with an OpenAI-compatible REST API on port 8080 (no Ollama required).
* **Backend (`backend`)**: Modular FastAPI application with:
  * Linux `stockfish` engine binary installed directly inside the image.
  * Layered architecture: `routers/` controllers, `services/` business logic, `db/repositories/` data access, and `schemas/` Pydantic DTOs.
  * Thread-safe Maia-3 + Clone MLP move prediction.
  * In-memory LRU caching for board SVG thumbnails.
  * Background queue worker for opponent clone training with Server-Sent Events (SSE) streaming.
  * Mounted host volume for `./models`.

---

## Quickstart

### 1. Launch the Stack (Automatic Model & Engine Download)
Stockfish, Maia-3, and Gemma 2B will automatically install and download inside the containers on first run:
```bash
cd revised
docker compose up --build -d
```
* **Stockfish**: Pre-installed in the backend container via package manager.
* **Maia-3 (5M)**: Pre-downloaded from Hugging Face during the backend Docker build.
* **Gemma 2 (2B)**: Automatically downloaded from Hugging Face by `llama.cpp:server` on first startup and cached in `./models`.

### 3. Verify Services
* **Backend Healthcheck**: `http://localhost:8000/health`
* **Swagger API Documentation**: `http://localhost:8000/docs`
* **Gemma Server**: `http://localhost:8080/v1/models`
* **PostgreSQL Port**: `localhost:5432` (`user: chess_user`, `password: chess_password`, `db: chess_db`)

---

## Authentication Endpoints

The backend provides complete self-hosted JWT authentication via HTTP-only secure cookies:

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/api/auth/register` | Register with `email`, `password` (min 6 chars), and optional `chess_com_username` |
| `POST` | `/api/auth/login` | Authenticate with `email` and `password`, sets HTTP-only `access_token` cookie |
| `POST` | `/api/auth/logout` | Clears `access_token` session cookie |
| `GET` | `/api/auth/me` | Returns logged-in user profile (`user_id`, `email`, `chess_com_username`) |
| `PATCH` | `/api/auth/profile` | Update user chess handles (`chess_com_username`, `lichess_username`) |
| `GET` | `/api/auth/google/login` | Redirects browser to Google OAuth consent screen |
| `GET` | `/api/auth/google/callback` | Exchanges Google auth code, issues JWT cookie, and redirects to `/app` |

---

## Directory Structure

```text
revised/
├── docker-compose.yml              # PostgreSQL + FastAPI + Gemma orchestration
├── .env                            # Environment variables
├── .env.example                    # Environment template
├── database/
│   └── init.sql                    # PostgreSQL DDL schema & indexes
├── models/                         # Mounted volume (models auto-download here on first boot)
│   └── .gitkeep
└── backend/
    ├── Dockerfile                  # Python 3.11 + Stockfish + PyTorch
    ├── requirements.txt            # Python dependencies
    ├── maia3/                      # Maia-3 transformer engine
    └── app/
        ├── main.py                 # FastAPI application & router mounting
        ├── config.py               # Settings & path management
        ├── dependencies.py         # Auth dependency (get_current_user)
        ├── db/                     # Connection pool & repositories (games, users, etc.)
        ├── ml/                     # Clone MLP neural network & feature extractors
        ├── routers/                # Endpoints (auth, games, analysis, clones, stream)
        ├── schemas/                # Pydantic v2 DTOs
        ├── services/               # Stockfish, Gemma, and Maia inference services
        └── workers/                # Background training worker & SSE broadcaster
```
