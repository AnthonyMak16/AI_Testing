# Faybl Playwright Automation  

This project contains Playwright + pytest automation suites for Faybl:
- `ybl_api_1517.py` – Export files formatting test.
- `ybl_api_1514.py` – PST canvas test
- `test_prototype.py` – Client form filling test with AI accuracy check.

---

## Requirements  
- Python 3.10+  
- Google Generative AI API (for `test_prototype.py`)

Python packages:
- Common: `pytest`, `playwright`
- For `ybl_api_1517.py`: `python-docx`
- For `test_prototype.py`: `google-generativeai`

---

## Project Structure  
- `ybl_api_1517.py`
- `ybl_api_1514.py`
- `test_prototype.py`
- `gemini_processor.py`
- `input_files/`
  - `input.json` – credentials, client metadata, Gemini API key, etc.
  - source files to upload.
- `output_files/`
- `screenshots/`

---

## Manual configuration

Before running any tests, update:

- The MANUAL CONFIGURATION sections at the top (e.g. `BASE_URL`, `BASE_PROJECT_DIR`, `REQUIRED_FILE_PATTERNS`, `NUM_RUNS`).
- `input_files/input.json` with your real Faybl login details, client names/IDs, and gemini_api_key for `test_prototype.py`.

---

## Setup
From the project directory:
```bash
cd YOUR_PROJECT_FOLDER

# install core dependencies
pip install pytest playwright python-docx google-generativeai

# install Playwright browsers
python -m playwright install

