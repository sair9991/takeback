# Setting Up Maia-3

This project relies on **Maia-3** (a transformer-based chess foundation model) to generate baseline logits for all legal moves.

Since the Maia-3 repository and its neural network weights (~21 MB) are large external dependencies, they are excluded from this Git repository via `.gitignore`. Follow the steps below to clone and install Maia-3 locally.

---

## 1. Clone the Maia-3 Repository

Clone the official `CSSLab/maia3` repository into the project root:

```bash
git clone https://github.com/CSSLab/maia3.git
```

This creates a local `maia3/` directory.

---

## 2. Install Maia-3 Dependencies & Package

Activate your virtual environment and install dependencies:

```bash
source .venv/bin/activate
pip install torch numpy huggingface_hub python-chess
pip install -e ./maia3 --no-deps
```

---

## 3. Download the Maia-3 Model Weights

Download the official `Maia3-5M` checkpoint from Hugging Face into `./models/`:

```bash
python -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='UofTCSSLab/Maia3-5M', filename='maia3-5m.pt', local_dir='./models')"
```

This downloads `maia3-5m.pt` into `./models/maia3-5m.pt`.

---

## 4. Verify Installation

Run this one-line sanity check:

```bash
python -c "from maia3.uci import load_model; from maia3.model_registry import resolve_model_spec; print('Maia-3 successfully imported and ready!')"
```

