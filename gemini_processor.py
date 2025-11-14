import google.generativeai as genai
import time
import os
from pathlib import Path

# ===================================== CONFIGURATION ===================================== #
DEFAULT_MODEL_NAME = "gemini-pro-latest"
# ========================================================================================= #

def upload_and_wait(path):
    print(f"Uploading {Path(path).name}...")
    file_obj = genai.upload_file(path=path)
    while file_obj.state.name == "PROCESSING":
        print(".", end="", flush=True)
        time.sleep(5)
        file_obj = genai.get_file(file_obj.name)
    print()
    if file_obj.state.name != "ACTIVE":
        raise Exception(f"File {file_obj.name} failed to process. State: {file_obj.state.name}")
    print(f" > {Path(path).name} is ACTIVE")
    return file_obj

def process_documents(api_key_string, file_paths_list, prompt_text, model_name=DEFAULT_MODEL_NAME):
    # 1. Configuration
    genai.configure(api_key=api_key_string)
    if not file_paths_list:
        raise Exception("No file paths provided for processing.")
    print(f"Starting to process {len(file_paths_list)} specific files...")

    # 2. Upload specified files
    uploaded_files = []
    try:
        for file_path in file_paths_list:
            if not Path(file_path).exists():
                print(f"Error: File not found at {file_path}. Skipping.")
                continue
            file_obj = upload_and_wait(file_path)
            uploaded_files.append(file_obj)

        if not uploaded_files:
            raise Exception("No valid files were uploaded successfully.")

        # 3. Generate Content
        print(f"All {len(uploaded_files)} files ACTIVE. Sending prompt to Gemini...")
        content_parts = uploaded_files + [prompt_text]
        
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(content_parts)
        generated_text = response.text.strip()
        
        # Clean the response
        if generated_text.startswith("```json"):
            json_start = generated_text.find('{')
            json_end = generated_text.rfind('}')
            if json_start != -1 and json_end != -1:
                generated_text = generated_text[json_start : json_end + 1]
        print("GEMINI RESPONSE RECEIVED.")
        if not generated_text:
             raise Exception("Failed to generate text from model.")
        return generated_text

    # 4. Cleanup
    finally:
        print("Starting cleanup...")
        for file_obj in uploaded_files:
            try:
                genai.delete_file(name=file_obj.name)
                print(f"Deleted: {file_obj.display_name}")
            except Exception:
                 print(f"Could not delete {file_obj.display_name}.")