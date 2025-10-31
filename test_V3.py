import json
import re
import time
from pathlib import Path
import pytest
from playwright.sync_api import Playwright, TimeoutError, expect
# =============================== EDITABLE VALUES =============================== #
BASE_URL = "https://staging.faybl.com"
SIGNIN_URL = f"{BASE_URL}/signin"
INPUT_DIR = Path(r"X:\XXXX\input_files")      # folder for files to upload
OUTPUT_DIR = Path(r"X:\XXXX\output_files")    # folder for downloaded files
JSON_PATH = Path(r"X:\XXXX\input_files\input.json")  # login + client data json
with JSON_PATH.open("r", encoding="utf-8") as f:
    data = json.load(f)
EMAIL = data["email"]
PASSWORD = data["password"]
PROTECTED_CODE = data["protectedCode"]
CLIENTS = data["clients"]
CLIENT_IDS = data["clientid"]
# ============================================================================== #
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
@pytest.mark.parametrize("client_index", [0])
def test_fact_find_and_kyc(playwright: Playwright, client_index: int) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    try:
        # Locators
        email_input = page.locator("input#email")
        password_input = page.locator("input#password")
        protected_input = page.locator("input#protectedCode")
        sign_in_button = page.locator("button.brand-origin-btn", has_text="Sign in")
        prompt_button = page.locator("button#send-message-button")
        chat_input = page.locator("textarea.rce-input.rce-input-textarea")
        next_button = page.get_by_role("button", name="Next")
        heading = page.locator("div.text-h4.font-semibold.text-text-lm-heading-color.overflow-hidden.text-ellipsis")
        spinner = page.locator("svg.text-status-in-progress-color.animate-spin")
        upload_button = page.locator('button[data-ga-id="Upload Files Button"]')
        upload_input = upload_button.locator('input[type="file"]')
        auto_form_filling_tab = page.get_by_role("tab", name="Auto Form Filling")
        editor = page.frame_locator('iframe[name="frameEditor"]')
        file_button = editor.locator("a#file")
        pdf_button = editor.locator("div.svg-format-pdf")

        # Test Steps
        page.goto(SIGNIN_URL, wait_until="domcontentloaded")
        expect(email_input).to_be_visible(timeout=10_000)
        expect(password_input).to_be_visible()
        expect(protected_input).to_be_visible()
        email_input.fill(EMAIL)
        password_input.fill(PASSWORD)
        protected_input.fill(PROTECTED_CODE)
        sign_in_button.click()
        try:
            expect(chat_input).to_be_visible(timeout=10_000)
        except Exception:
            print("Login failed, please check credentials.")
            page.screenshot(path="login-failed.png", full_page=True)
            raise
        client_name = CLIENTS[client_index]
        page.fill(
            "textarea.rce-input.rce-input-textarea",
            f"/xplan-get-client-details for {client_name}",
        )
        page.keyboard.press("Enter")
        client_fetch_start = time.time()
        try:
            expect(next_button).to_be_visible(timeout=60_000)
        except Exception:
            print("Xplan script timeout after 60 seconds.")
            page.screenshot(path="Xplan-timeout.png", full_page=True)
            raise
        next_button.click()
        page.wait_for_timeout(3_000)
        client_id_cell = page.get_by_role("cell", name=str(CLIENT_IDS[client_index]))
        client_data_entry = page.get_by_role(
            "button", name=re.compile(r"xplan - get client details", re.IGNORECASE)
        )
        try:
            visible = client_id_cell.is_visible(timeout=1_000)
        except TimeoutError:
            visible = False
        if not visible:
            client_data_entry.click()
        expect(client_id_cell).to_be_visible(timeout=300_000)
        client_id_cell.click()
        expect(next_button).to_be_visible(timeout=10_000)
        next_button.click()
        try:
            expect(heading).to_be_visible(timeout=900_000)
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(OUTPUT_DIR / "client_details.png"), full_page=True)
            elapsed = time.time() - client_fetch_start
            print(f"Retrieved client details for {client_name} in {elapsed:.2f}s")
        except Exception:
            print("Timeout after 15 minutes waiting for Faybl to retrieve client details.")
            page.screenshot(path="xplan-timeout.png", full_page=True)
            raise
        all_files = listfiles(INPUT_DIR)
        matches = [
            file_path
            for file_path in all_files
            if file_path.stem.strip().lower().endswith("clientprofileform")
        ]
        if not matches:
            raise FileNotFoundError(
                f"No file in {INPUT_DIR} with a name ending in 'ClientProfileForm' (ignoring extension)."
            )
        if len(matches) == 1:
            files_to_upload = [matches[0]]
        else:
            files_to_upload = [
                max(matches, key=lambda path: path.stat().st_mtime)
            ]
        upload_start = time.time()
        upload_input.set_input_files([str(path) for path in files_to_upload])
        expect(prompt_button).to_be_enabled(timeout=120_000)
        prompt_button.hover()
        prompt_button.click()
        upload_duration = time.time() - upload_start
        log_upload_report(files_to_upload)
        print(f"{len(files_to_upload)} files uploaded in {upload_duration:.2f}s")
        page.wait_for_timeout(5_000)
        file_entry = (
            page.locator("div.font-semibold.text-main-body.text-text-lm-heading-color")
            .filter(has_text="ClientProfileForm")
        )
        try:
            visible = auto_form_filling_tab.is_visible(timeout=1_000)
        except TimeoutError:
            visible = False
        if not visible:
            file_entry.click()
        page.wait_for_timeout(3_000)
        expect(auto_form_filling_tab).to_be_visible(timeout=30_000)
        auto_form_filling_tab.click()
        try:
            spinner.first.wait_for(state="visible", timeout=10_000)
            autofill_start = time.time()
            spinner.first.wait_for(state="detached", timeout=900_000)
            print(f"Auto form filling completed in {time.time() - autofill_start:.2f}s")
        except Exception:
            print("Timeout after 15 minutes waiting for Faybl to fill the form.")
            page.screenshot(path="autofill-timeout.png", full_page=True)
            raise
        expect(file_button).to_be_visible(timeout=300_000)
        page.wait_for_timeout(5_000)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUTPUT_DIR / "filled_form.png"), full_page=True)
        file_button.click()
        page.wait_for_timeout(3_000)
        with page.expect_download() as download_info:
            pdf_button.click()
        download = download_info.value
        suggested_name = download.suggested_filename
        save_path = OUTPUT_DIR / suggested_name
        download.save_as(str(save_path))
    finally:
        context.close()
        browser.close()

