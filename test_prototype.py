import json
import re
import time
import csv
from pathlib import Path
import pytest
import gemini_processor
from playwright.sync_api import Playwright, TimeoutError, expect

# ==================================MANUAL CONFIGURATION ================================== #
BASE_URL = "https://staging.faybl.com"
BASE_PROJECT_DIR = Path(r"C:\Users\Tony\project")
# Files to upload to Faybl, file name must contain one of these patterns (case insensitive, can be partial)
REQUIRED_FILE_PATTERNS = [
    "ClientProfileForm",
    "SOA",
]
NUM_RUNS = 2 # Number of times to run the test
# ========================================================================================= #

SIGNIN_URL = f"{BASE_URL}/signin"
INPUT_DIR = BASE_PROJECT_DIR / "input_files" # folder for input files
OUTPUT_DIR = BASE_PROJECT_DIR / "output_files" / "test_prototype" # folder for downloaded files and later send to Gemini
SS_DIR = BASE_PROJECT_DIR / "screenshots" / "test_prototype"# folder for screenshots
SS_ERR_DIR = SS_DIR / "errors" # folder for error screenshots
JSON_PATH = INPUT_DIR / "input.json" # login + client data json
TIME_DATA_CSV = OUTPUT_DIR / "test_prototype_performance_metrics.csv" # Path for the CSV

TOTAL_RUNS = 0
SUCCESSFUL_RUNS = 0

# Gemini Configuration
MODEL_NAME = "gemini-pro-latest"
GEMINI_PROMPT = """
Goal:
Compare each fillable PDF field to the TXT data and classify as Correct, Incorrect, Empty, or Unmappable (ignore Unmappable in output and accuracy).

Field name with context:
Report field_name as a hierarchical path using the closest labels:
Section > Subsection > Repeating-block label > Field label
Include table row/column headers if relevant.
For radios/checkboxes, use the group label for the field name; do not append the selected option.

Normalization (apply to both sides before comparing):
Trim whitespace; case-insensitive.
Strip decorative punctuation and helper text.
Numbers/currency/percentages: ignore separators/symbols; treat equivalent numeric forms as equal.
Dates: accept common formats; normalize to YYYY-MM-DD.
Booleans/radios/checkboxes: unify to checked/selected vs unchecked.
Addresses: ignore case/redundant punctuation; allow common abbreviations.
Empty = null/blank/whitespace-only or unselected option groups.

Decisions:
Correct: normalized values match.
Incorrect: non-empty but mismatched.
Empty: PDF empty but TXT has a value.
Unmappable: no reasonable TXT key → ignore.

Accuracy:
accuracy = round(100 * N_correct / max(1, N_eval), 2) where N_eval = Correct + Incorrect + Empty. Format as "x.xx%".

Output (just python dictionary with exact keys, nothing extra):
{
"accuracy": "x.xx%",
"incorrect_fields": [
    {"field_name": "<Section > Subsection > Block > Field>", "correct_value": "<TXT value>"}
],
"empty_fields": [
    {"field_name": "<Section > Subsection > Block > Field>", "correct_value": "<TXT value>"}
]
}

Process:
Extract all PDF fields/values.
Parse TXT to key→value dict (allow simple alias/fuzzy matching).
Map each PDF field to a TXT key; classify (Correct/Incorrect/Empty) or mark Unmappable.
Compute accuracy; return only the Python dictionary.
"""
# ========================================================================================= #

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
CLIENTS = data["clients"]
CLIENT_IDS = data["clientid"]
GEMINI_API_KEY = data["gemini_api_key"]

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
            w.writerow(["PROTOTYPE TEST"])
            w.writerow([])
            w.writerow(["SUMMARY"])
            w.writerow(["Login duration (s)", f"{duration:.2f}"])
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

def parse_verification_rows(client_name, run_number, json_report_string, document_name):
    """Return (rows, accuracy) for a single document's verification."""
    try:
        if json_report_string.startswith("```"):
            json_start = json_report_string.find('{')
            json_end = json_report_string.rfind('}')
            if json_start != -1 and json_end != -1:
                json_report_string = json_report_string[json_start : json_end + 1]
        data = json.loads(json_report_string)
        accuracy = data.get("accuracy", "N/A")
        incorrect_fields = data.get("incorrect_fields", [])
        empty_fields = data.get("empty_fields", [])
        rows_to_write = []
        base_row = {"client": client_name, "run": run_number, "document": document_name}
        for item in incorrect_fields:
            rows_to_write.append({**base_row, "error_type": "Incorrect",
                                  "field_name": item.get("field_name", "Unknown"),
                                  "correct_value": item.get("correct_value", "")})
        for item in empty_fields:
            rows_to_write.append({**base_row, "error_type": "Empty",
                                  "field_name": item.get("field_name", "Unknown"),
                                  "correct_value": item.get("correct_value", "")})
        return rows_to_write, accuracy
    except json.JSONDecodeError:
        print(f"Error: Could not parse cleaned Gemini JSON for {document_name}.")
        return [], "N/A"
    except Exception:
        print(f"Error generating verification rows for {document_name}.")
        return [], "N/A"

@pytest.mark.parametrize("client_index", range(len(CLIENTS)))
def test_fact_find_and_kyc(playwright: Playwright, client_index: int, auth_state) -> None:
    global TOTAL_RUNS, SUCCESSFUL_RUNS
    time_data = [] # store time data
    verification_rows = [] # store verification results for this client
    verification_accuracy = {} # store accuracy per (run, document)
    error_msg = None # store error message if any
    client_name = CLIENTS[client_index]
    print(f"\n\n========== Testing for Client: {client_name} ==========")
    for run_number in range(1, NUM_RUNS + 1):
        print(f"\n--- Starting Run {run_number}/{NUM_RUNS} ---")
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

            # 2. Auth (reused session)
            current_step = "Login"
            print("Using session auth...")
            page.goto(BASE_URL, wait_until="domcontentloaded")
            expect(chat_input).to_be_visible(timeout=10_000)
            
            # 3. Get client details from Xplan
            current_step = "Fetch Client Details From Xplan"
            print("Fetching client details from Xplan...")
            chat_input.fill(f"/xplan-get-client-details for {client_name}")
            data_fetch_start = time.time()  # Time client data fetch duration
            page.keyboard.press("Enter")
            expect(next_button).to_be_visible(timeout=60_000)
            next_button.click()
            client_id_cell = page.get_by_role("cell", name=str(CLIENT_IDS[client_index]))
            client_data_entry = page.get_by_role(
                "button", name=re.compile(r"xplan - get client details", re.IGNORECASE)
            )
            
            # Try opening the Xplan result list if the cell isn't visible yet
            if not client_id_cell.is_visible():
                client_data_entry.click()
            expect(client_id_cell).to_be_visible(timeout=300_000)
            page.screenshot(path=str(SS_DIR / "client_list.png"), full_page=True)
            client_id_cell.click()

            # Proceed to next step
            expect(next_button).to_be_visible(timeout=30_000)
            next_button.click()
            expect(heading).to_be_visible(timeout=900_000)
            page.screenshot(path=str(SS_DIR / "client_details.png"), full_page=True)
            duration = time.time() - data_fetch_start
            print(f"Retrieved client details for {client_name}. Elapsed: {duration:.2f}s")
            time_data.append({
                "client": client_name, "run": run_number, "action": "Fetch Client Details", "duration": duration
            })
            
            # Download Xplan result file
            current_step = "Download Xplan Result"
            print("Starting Xplan result download...")
            expect(download_result).to_be_visible(timeout=10_000)
            xplan_download_start = time.time() # Time download duration
            with page.expect_download() as download_info:
                download_result.click()
            download = download_info.value
            suggested_name = download.suggested_filename
            base = Path(suggested_name)
            result_save_path = OUTPUT_DIR / f"{base.stem}_client{client_index + 1}_run{run_number}{base.suffix}"
            download.save_as(str(result_save_path))
            duration = time.time() - xplan_download_start
            print(f"Xplan result downloaded to: {result_save_path.name}. Elapsed: {duration:.2f}s")
            time_data.append({
                "client": client_name, "run": run_number, "action": "Download Xplan result", "duration": duration
            })

            # 4. Select files to upload based on REQUIRED_FILE_PATTERNS
            current_step = "File Upload"
            print("Selecting files to upload...")
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
            for idx, path in enumerate(files_to_upload, start=1):
                current_step = f"Processing Document: {path.name}"
                print(f"Uploading file {idx}/{len(files_to_upload)}: {path.name}")
                log_upload_report([path])
                upload_input.set_input_files(str(path))
                upload_start = time.time()
                expect(prompt_button).to_be_enabled(timeout=120_000)
                prompt_button.hover()
                prompt_button.click()
                duration = time.time() - upload_start
                print(f"{path.name} uploaded. Elapsed: {duration:.2f}s")
                time_data.append({
                    "client": client_name, "run": run_number, "action": f"File Upload - {path.name}", "duration": duration
                })
                page.wait_for_timeout(5_000)

                # 5. Wait and confirm Auto form filling completion
                current_step = f"Auto Form Filling: {path.name}"
                print(f"Starting auto form filling for {path.name}...")
                file_entry = (
                    page.locator("div.font-semibold.text-main-body.text-text-lm-heading-color")
                    .filter(has_text=path.name.replace(" ", "_"))
                )
                if not auto_form_filling_tab.is_visible():
                    file_entry.click()
                page.wait_for_timeout(5_000)
                expect(auto_form_filling_tab).to_be_visible(timeout=30_000)
                auto_form_filling_tab.click()
                spinner.first.wait_for(state="visible", timeout=20_000)
                autofill_start = time.time() # Time autofill duration
                spinner.first.wait_for(state="detached", timeout=900_000)
                duration = time.time() - autofill_start
                print(f"Auto form filling completed for {path.name}, Elapsed: {duration:.2f}s")
                time_data.append({
                    "client": client_name, "run": run_number, "action": f"Autofill-{path.name}", "duration": duration
                })

                # 6. Download filled form as PDF
                current_step = f"Download document: {path.name}"
                print(f"Starting download of filled document for {path.name}")
                expect(file_button).to_be_visible(timeout=300_000)
                page.wait_for_timeout(5_000)
                page.screenshot(path=str(SS_DIR / "filled_form.png"), full_page=True)
                file_button.click()
                page.wait_for_timeout(3_000)
                profileform_download_start = time.time() # Time download duration
                with page.expect_download() as download_info:
                    pdf_button.click()
                download = download_info.value
                suggested_name = download.suggested_filename
                base = Path(suggested_name)
                pdf_save_path = OUTPUT_DIR / f"{base.stem}_client{client_index + 1}_run{run_number}{base.suffix}"
                download.save_as(str(pdf_save_path))
                duration = time.time() - profileform_download_start
                print(f"Downloaded {suggested_name}. Elapsed: {duration:.2f}s")
                time_data.append({
                    "client": client_name, "run": run_number, "action": f"Download-{suggested_name}", "duration": duration
                })
                page.wait_for_timeout(3_000)

                # 7. Call Gemini processor using the downloaded files in OUTPUT_DIR
                current_step = "Gemini Verification"
                print("\n" + "="*50)
                print("Starting Gemini verification process...")
                files_to_process = [result_save_path, pdf_save_path]
                verification_report = gemini_processor.process_documents(
                    api_key_string=GEMINI_API_KEY,
                    file_paths_list=files_to_process,
                    prompt_text=GEMINI_PROMPT,
                    model_name=MODEL_NAME
                )
                rows, acc = parse_verification_rows(client_name, run_number, verification_report, path.name)
                verification_rows.extend(rows)
                verification_accuracy[(run_number, path.name)] = acc
                print(f"Gemini verification for Run {run_number} complete.")
                print("\n" + "="*50)
                print("Form filling accuracy report:")
                print(verification_report)
                print("\n" + "="*50)
                page.wait_for_timeout(5_000)
        
        # Error report
        except Exception as e:
            print(f"Run {run_number} FAILED at step: {current_step} for {client_name}. Error: {e}")
            page.screenshot(path=str(SS_ERR_DIR / f"FAIL_{client_name}_Run{run_number}_Step_{current_step}.png"))
            time_data.append({
                "client": client_name,
                "run": run_number,
                "action": f"FAILED at {current_step}",
                "duration": None
            })
            if error_msg is None:
                error_msg = f"Run {run_number} failed at {current_step} for {client_name}. Error {e}"
        finally:
            context.close()
            browser.close()
    
    # Append data to the CSV
    with open(TIME_DATA_CSV, mode='a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        runs = sorted({row["run"] for row in time_data})
        
        # Performance report
        for rn in runs:
            w.writerow([f"Client: {client_name} | Run: {rn}"])
            w.writerow(["TIME PERFORMANCE"])
            w.writerow(["Action", "Duration (s)"])
            for row in time_data:
                if row["run"] == rn:
                    duration_val = "" if row["duration"] is None else f"{row['duration']:.2f}"
                    w.writerow([row["action"], duration_val])

            # Verification sub-section (group by document; document as subheader; accuracy on its own row)
            w.writerow([])
            w.writerow(["AUTO FILL PERFORMANCE"])
            doc_groups = {}
            doc_order = []
            for vrow in verification_rows:
                if vrow.get("run") == rn:
                    doc_name = vrow.get("document", "")
                    if doc_name not in doc_groups:
                        doc_groups[doc_name] = {"rows": []}
                        doc_order.append(doc_name)
                    doc_groups[doc_name]["rows"].append(vrow)
            for doc_name in doc_order:
                w.writerow([f"Document: {doc_name}"])
                acc = verification_accuracy.get((rn, doc_name))
                w.writerow([f"Accuracy: {acc if acc is not None else 'N/A'}"])
                w.writerow(["error_type", "field_name", "correct_value"])
                for vrow in doc_groups[doc_name]["rows"]:
                    w.writerow([
                        vrow.get("error_type", ""),
                        vrow.get("field_name", ""),
                        vrow.get("correct_value", ""),
                    ])
                w.writerow([])

    # Rewrite the CSV
    if client_index == len(CLIENTS) - 1:
        with open(TIME_DATA_CSV, mode="r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        total_runs = 0
        successful_runs = 0
        total_time = 0.0
        i = 0
        while i < len(lines):
            line = lines[i]
            parts = line.split(",", 1)
            if len(parts) == 2:
                try:
                    total_time += float(parts[1])
                except ValueError:
                    pass
            if line.startswith("Client:"):
                total_runs += 1
                run_failed = False
                i += 1
                while i < len(lines) and not lines[i].startswith("Client:"):
                    sub_line = lines[i]
                    sub_parts = sub_line.split(",", 1)
                    if len(sub_parts) == 2:
                        try:
                            total_time += float(sub_parts[1])
                        except ValueError:
                            pass
                    if sub_line.startswith("FAILED at "):
                        run_failed = True
                    i += 1
                if not run_failed:
                    successful_runs += 1
            else:
                i += 1
        success_rate = 100 * successful_runs / total_runs if total_runs else 0.0
        first_client_idx = next(
            (idx for idx, line in enumerate(lines) if line.startswith("Client:")),
            len(lines),
        )
        header_and_login = lines[:first_client_idx]
        per_run_lines = lines[first_client_idx:]
        summary_lines = [
            f"Total runs,{total_runs}",
            f"Successful runs,{successful_runs}",
            f"Success rate,{success_rate:.2f}%",
            f"Total time (s),{total_time:.2f}",
            "",
        ]
        with open(TIME_DATA_CSV, mode="w", encoding="utf-8", newline="") as f:
            for line in header_and_login:
                f.write(line + "\n")
            for line in summary_lines:
                f.write(line + "\n")
            for line in per_run_lines:
                f.write(line + "\n")
    print(f"Performance data for {client_name} appended to {TIME_DATA_CSV.name}")
    
    if error_msg:
        pytest.fail(error_msg)
