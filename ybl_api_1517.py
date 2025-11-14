import json
import re
import time
import csv
from pathlib import Path
import pytest
from docx import Document
from playwright.sync_api import Playwright, TimeoutError, expect

# ==================================MANUAL CONFIGURATION ================================== #
BASE_URL = "https://app.faybl.com"
BASE_PROJECT_DIR = Path(r"C:\Users\Tony\project")
# Files to upload to Faybl, file name must contain one of these patterns (case insensitive, can be partial)
REQUIRED_FILE_PATTERNS = [
    "Letter_of_Recommendation",
]
NUM_RUNS = 2 # Number of times to run the test
# ========================================================================================= #

SIGNIN_URL = f"{BASE_URL}/signin"
INPUT_DIR = BASE_PROJECT_DIR / "input_files" # folder for input files
OUTPUT_DIR = BASE_PROJECT_DIR / "output_files" / "ybl_api_1517" # folder for downloaded files and later send to Gemini
SS_DIR = BASE_PROJECT_DIR / "screenshots" / "ybl_api_1517" # folder for screenshots
SS_ERR_DIR = SS_DIR / "errors" # folder for error screenshots
JSON_PATH = INPUT_DIR / "input.json" # login + client data json
TIME_DATA_CSV = OUTPUT_DIR / "test_1517_performance_metrics.csv" # Path for the new CSV

TOTAL_RUNS = 0
SUCCESSFUL_RUNS = 0

if not INPUT_DIR.exists() or not INPUT_DIR.is_dir():
    raise FileNotFoundError(
        f"Input folder not found: {INPUT_DIR}. Please create it and place files to upload."
    )
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
SS_DIR.mkdir(parents=True, exist_ok=True)
SS_ERR_DIR.mkdir(parents=True, exist_ok=True)

with JSON_PATH.open("r", encoding="utf-8") as f:
    data = json.load(f)
EMAIL = data["email"]
PASSWORD = data["password"]
PROTECTED_CODE = data["protectedCode"]

@pytest.fixture(scope="session")
def auth_state(playwright: Playwright):
    """Log in once and return storage_state for reuse across tests."""
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    try:
        # Locators for login
        email_input = page.locator("input#email")
        password_input = page.locator("input#password")
        protected_input = page.locator("input#protectedCode")
        sign_in_button = page.locator("button.brand-origin-btn", has_text="Sign in")
        chat_input = page.locator("textarea.rce-input.rce-input-textarea")

        # Proceed to login
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        expect(email_input).to_be_visible(timeout=10_000)
        expect(password_input).to_be_visible(timeout=10_000)
        email_input.fill(EMAIL)
        password_input.fill(PASSWORD)
        if protected_input.is_visible():
            protected_input.fill(PROTECTED_CODE)
        expect(sign_in_button).to_be_visible(timeout=10_000)
        expect(sign_in_button).to_be_enabled(timeout=10_000)
        login_start = time.time()
        sign_in_button.click()
        expect(chat_input).to_be_visible(timeout=120_000)
        duration = time.time() - login_start
        with open(TIME_DATA_CSV, mode='a', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(["TEST FORMATTING IN EXPORTS"])
            w.writerow([])
            w.writerow(["SUMMARY"])
            w.writerow(["Login duration", f"{duration:.2f}"])
        return context.storage_state()
    except Exception as e:
        print(f"Login failed. Error: {e}")
        page.screenshot(path=str(SS_ERR_DIR / "FAIL_Session_Login.png"))
        with open(TIME_DATA_CSV, mode="a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Login failed, please check credentials and restart test."])
        raise
    finally:
        context.close()
        browser.close()

def listfiles(directory: Path) -> list[Path]:
    if not directory.exists():
        raise FileNotFoundError(f"Folder not found: {directory}")
    files = [p for p in directory.iterdir() if p.is_file() and not p.name.startswith(".")]
    if not files:
        raise FileNotFoundError(f"No files found in {directory}")
    return files

def format_bytes(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    precision = 1 if value < 10 and idx > 0 else 0
    return f"{value:.{precision}f} {units[idx]}"

def log_upload_report(files: list[Path]) -> None:
    print(f"Uploading {len(files)} file(s):")
    for index, file_path in enumerate(files, start=1):
        size = file_path.stat().st_size
        print(f" [{index}] {file_path.name} - {format_bytes(size)} - {file_path}")


@pytest.mark.parametrize("run_number", range(1, NUM_RUNS + 1))
def test_formatting_in_exports (playwright: Playwright, run_number: int, auth_state) -> None:
    global TOTAL_RUNS, SUCCESSFUL_RUNS
    time_data = [] # store time data
    table_counts = {}
    error_msg = None # store error message if any
    run_failed = False
    TOTAL_RUNS += 1
    print(f"\n\n========== TEST RUN {run_number}/{NUM_RUNS} ==========")
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True, storage_state=auth_state)
    page = context.new_page()
    current_step = "Initialization"

    try:
        # 1. Locators
        current_step = "Locators Setup"
        email_input = page.locator("input#email")
        password_input = page.locator("input#password")
        protected_input = page.locator("input#protectedCode")
        sign_in_button = page.locator("button.brand-origin-btn", has_text="Sign in")
        prompt_button = page.locator("button#send-message-button")
        chat_input = page.locator("textarea.rce-input.rce-input-textarea")
        download_result = page.get_by_role("link", name="Result")
        next_button = page.get_by_role("button", name="Next")
        heading = page.locator("div.text-h4.font-semibold.text-text-lm-heading-color.overflow-hidden.text-ellipsis")
        spinner = page.locator("svg.text-status-in-progress-color.animate-spin")
        upload_button = page.locator('button[data-ga-id="Upload Files Button"]')
        upload_input = upload_button.locator('input[type="file"]')
        auto_form_filling_tab = page.get_by_role("tab", name="Auto Form Filling")
        editor = page.frame_locator('iframe[name="frameEditor"]')
        file_button = editor.locator("a#file")
        pdf_button = editor.locator("div.svg-format-pdf")
        export_canvas = page.locator('svg[id^="export-canvas-"]')
        export_options = page.get_by_role("button", name="Export options")
        export_word = page.get_by_role("button", name="Export as Word")


        # 2. Auth (reused session)
        current_step = "Login"
        print("Using session auth...")
        page.goto(BASE_URL, wait_until="domcontentloaded")
        expect(chat_input).to_be_visible(timeout=10_000)
        
        # 3. Select files to upload based on REQUIRED_FILE_PATTERNS
        current_step = "File Upload"
        print("Selecting file to upload...")
        all_files = listfiles(INPUT_DIR)
        files_to_upload = []
        for pattern in REQUIRED_FILE_PATTERNS:
            matches = [
                f for f in all_files
                if pattern.lower() in f.stem.lower()
            ]
            if not matches:
                print(f"  [WARNING] Could not find any file matching pattern: '{pattern}'")
                continue
            newest_match = max(matches, key=lambda p: p.stat().st_mtime)
            files_to_upload.append(newest_match)
            print(f"  > Found match for '{pattern}': {newest_match.name}")
        files_to_upload = list(dict.fromkeys(files_to_upload)) # Ensure unique files only
        if not files_to_upload:
            raise FileNotFoundError("No valid files found from ANY of the required patterns.")
        
        # Proceed to upload           
        current_step = "Upload File"
        print("Uploading file to Faybl...")
        upload_input.set_input_files([str(path) for path in files_to_upload])
        upload_start = time.time()
        expect(prompt_button).to_be_enabled(timeout=120_000)
        prompt_button.hover()
        prompt_button.click()
        log_upload_report(files_to_upload)        
        duration = time.time() - upload_start
        print(f"{len(files_to_upload)} files uploaded. Elapsed: {duration:.2f}s")
        time_data.append({
            "run": run_number, "action": f"File Upload ", "duration": duration
        })
        page.wait_for_timeout(5_000)

        # 4. Wait for Faybl to process the document
        current_step = "Process Document"
        print(f"Waiting for Faybl to process document...")
        spinner.first.wait_for(state="visible", timeout=10_000)
        process_start = time.time() # Time process duration
        spinner.first.wait_for(state="detached", timeout=900_000)        
        expect(heading).to_be_visible(timeout=10_000)
        page.screenshot(path=str(SS_DIR / f"summary_{REQUIRED_FILE_PATTERNS[0]}.png"), full_page=True)
        duration = time.time() - process_start
        print(f"Document process completed, Elapsed: {duration:.2f}s")
        time_data.append({
            "run": run_number, "action": "Autofill", "duration": duration
        })

        # 5. Send prompt to Faybl
        current_step = "Send Prompt"
        print("Sending prompt to Faybl...")
        chat_input.fill("Fill the client’s details and all buy/sell trades into a transaction form using this document.")
        prompt_start = time.time()  # Time client data fetch duration
        page.keyboard.press("Enter")
        expect(export_canvas).to_be_visible(timeout=120_000)
        duration = time.time() - prompt_start
        print(f"System response received. Elapsed: {duration:.2f}s")
        time_data.append({
            "run": run_number, "action": "Prompt Response", "duration": duration
        })
        page.wait_for_timeout(3_000)
        page.screenshot(path=str(SS_DIR / f"filled_{REQUIRED_FILE_PATTERNS[0]}.png"), full_page=True)
        export_canvas.click()
        expect(export_options).to_be_visible(timeout=10_000)
        page.screenshot(path=str(SS_DIR / f"canvas_{REQUIRED_FILE_PATTERNS[0]}.png"), full_page=True)
        export_options.click()
        page.wait_for_timeout(3_000)

        # 6. Export Word
        expect(export_word).to_be_visible(timeout=10_000)
        word_download_start = time.time() # Time download duration
        with page.expect_download() as download_info:
            export_word.click()
        download = download_info.value
        suggested_name = download.suggested_filename
        base = Path(suggested_name)
        word_save_path = OUTPUT_DIR / f"{base.stem}_run{run_number}{base.suffix}"
        download.save_as(str(word_save_path))
        duration = time.time() - word_download_start
        print(f"Downloaded {suggested_name}. Elapsed: {duration:.2f}s")
        time_data.append({
            "run": run_number, "action": f"Download-{suggested_name}", "duration": duration
        })
        page.wait_for_timeout(3_000)

        # 7. Check for tables in word content
        doc = Document(str(word_save_path))
        table_count = len(doc.tables)
        table_counts[run_number] = table_count
        print(f"Word tables found in {word_save_path.name}: {table_count}")
    
    # Error report
    except Exception as e:
        print(f"Run {run_number} FAILED at step: {current_step}. Error: {e}")
        page.screenshot(path=str(SS_ERR_DIR / f"FAIL_Run{run_number}_Step_{current_step}.png"))
        time_data.append({
            "run": run_number,
            "action": f"FAILED at {current_step}",
            "duration": None
        })
        if error_msg is None:
            error_msg = f"Run {run_number} failed at {current_step}. Error: {e}"
        run_failed = True

    finally:
        context.close()
        browser.close()

    if not run_failed:
        SUCCESSFUL_RUNS += 1

    # Append data to the CSV
    with open(TIME_DATA_CSV, mode='a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        runs = sorted({row["run"] for row in time_data})
        for rn in runs:
            w.writerow([f"Run: {rn}"])
            w.writerow(["TIME PERFORMANCE"])
            w.writerow(["Action", "Duration (s)"])
            for row in time_data:
                if row["run"] == rn:
                    duration_val = "" if row["duration"] is None else f"{row['duration']:.2f}"
                    w.writerow([row["action"], duration_val])
            w.writerow([])
            w.writerow([f"Tables in word export: {table_counts.get(rn, 'N/A')}"])
            w.writerow([])

    # Rewrite the CSV
    if run_number == NUM_RUNS:
        success_rate = 100 * SUCCESSFUL_RUNS / TOTAL_RUNS if TOTAL_RUNS else 0.0
        with open(TIME_DATA_CSV, mode='r', encoding='utf-8') as f:
            lines = f.read().splitlines()
        total_time = 0.0
        for line in lines:
            parts = line.split(",", 1)
            if len(parts) == 2:
                try:
                    total_time += float(parts[1])
                except ValueError:
                    pass
        first_run_idx = next(
            (i for i, line in enumerate(lines) if line.startswith("Run:")),
            len(lines),
        )
        header_and_login = lines[:first_run_idx]
        per_run_lines = lines[first_run_idx:]
        summary_lines = [
            f"Total runs,{TOTAL_RUNS}",
            f"Successful runs,{SUCCESSFUL_RUNS}",
            f"Success rate,{success_rate:.2f}%",
            f"Total time (s),{total_time:.2f}",
            "",
        ]
        with open(TIME_DATA_CSV, mode='w', encoding='utf-8', newline='') as f:
            for line in header_and_login:
                f.write(line + "\n")
            for line in summary_lines:
                f.write(line + "\n")
            for line in per_run_lines:
                f.write(line + "\n")
    print(f"Performance data appended to {TIME_DATA_CSV.name}")
    
    if error_msg:
        pytest.fail(error_msg)
