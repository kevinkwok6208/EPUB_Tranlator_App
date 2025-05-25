import tkinter as tk
from tkinter import filedialog, ttk, scrolledtext
import os
import shutil
import sys
import warnings
import threading
import subprocess
from io import StringIO
import json
import epub_processor 
import file_manager
import text_extractor
import translator
import time
import traceback
from file_manager import find_subfolder_path

def get_base_path():
    """Return the base path for the application (handles PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.getcwd()

class StreamRedirector:
    """Redirects stdout and stderr to the ScrolledText widget with buffered updates."""
    def __init__(self, text_widget, original_stream):
        self.text_widget = text_widget
        self.original_stream = original_stream
        self.buffer = StringIO()
        self.text_buffer = []
        self.update_interval = 100  # ms
        self._schedule_update()

    def write(self, text):
        self.text_buffer.append(text)
        if self.original_stream is not None and hasattr(self.original_stream, 'write'):
            try:
                self.original_stream.write(text)
            except Exception:
                pass
        self.buffer.write(text)

    def _update_text(self):
        if self.text_buffer:
            combined_text = ''.join(self.text_buffer)
            self.text_buffer = []
            try:
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, combined_text)
                self.text_widget.yview(tk.END)
                self.text_widget.config(state='disabled')
            except Exception:
                pass
        self._schedule_update()

    def _schedule_update(self):
        try:
            self.text_widget.after(self.update_interval, self._update_text)
        except Exception:
            pass

    def flush(self):
        self.buffer.flush()
        if self.original_stream is not None and hasattr(self.original_stream, 'flush'):
            try:
                self.original_stream.flush()
            except Exception:
                pass

class TranslationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB Translator")
        self.root.geometry("600x500")
        self.root.attributes('-topmost', False)
        self.is_translating = False
        
        self.base_dir = get_base_path()
        self.output_dir = os.path.join(self.base_dir, "output")
        self.temp_dir = os.path.join(self.base_dir, "temp")
        self.credential_dir = os.path.join(self.base_dir, "credential")
        
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        ttk.Label(self.main_frame, text="EPUB File:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.file_entry = ttk.Entry(self.main_frame, width=50)
        self.file_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_file).grid(row=0, column=2, padx=5)
        
        ttk.Label(self.main_frame, text="Platform:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.platform_var = tk.StringVar(value="kindle")
        self.platform_menu = ttk.Combobox(self.main_frame, textvariable=self.platform_var, values=["kindle", "kobo"], state="readonly", width=47)
        self.platform_menu.grid(row=1, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(self.main_frame, text="API URL:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.api_url_entry = ttk.Entry(self.main_frame, width=50)
        self.api_url_entry.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(self.main_frame, text="API Key:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.api_key_entry = ttk.Entry(self.main_frame, width=50)
        self.api_key_entry.grid(row=3, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        ttk.Label(self.main_frame, text="Model:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.model_entry = ttk.Entry(self.main_frame, width=50)
        self.model_entry.grid(row=4, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        self.load_credentials()
        
        self.translate_button = ttk.Button(self.main_frame, text="Translate", command=self.translate)
        self.translate_button.grid(row=5, column=1, pady=10)
        ttk.Button(self.main_frame, text="Start New Book", command=self.clear_temp).grid(row=5, column=2, pady=10)
        ttk.Button(self.main_frame, text="Focus Window", command=self.focus_window).grid(row=5, column=0, pady=10)
        ttk.Button(self.main_frame, text="Reveal Output", command=self.reveal_output).grid(row=6, column=1, pady=10)
        
        ttk.Label(self.main_frame, text="Log:").grid(row=7, column=0, sticky=tk.W, pady=5)
        self.log_text = scrolledtext.ScrolledText(self.main_frame, width=60, height=15, wrap=tk.WORD)
        self.log_text.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.log_text.config(state='disabled')
        
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(8, weight=1)
        
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.credential_dir, exist_ok=True)
        
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = StreamRedirector(self.log_text, self.original_stdout)
        sys.stderr = StreamRedirector(self.log_text, self.original_stderr)
        
        warnings.showwarning = self.redirect_warning
        
        self.root.after(1000, self._check_responsiveness)

    def load_credentials(self):
        credential_file = os.path.join(self.credential_dir, "credential.json")
        try:
            if os.path.exists(credential_file):
                with open(credential_file, 'r') as f:
                    credentials = json.load(f)
                    self.api_url_entry.insert(0, credentials.get('api_url', 'Replace by your API URL'))
                    self.api_key_entry.insert(0, credentials.get('api_key', 'Replace by your API key'))
                    self.model_entry.insert(0, credentials.get('model', 'Replace by your model'))
                    self.write("Credentials loaded successfully.\n")
            else:
                self.api_url_entry.insert(0, "Replace by your API URL")
                self.api_key_entry.insert(0, "Replace by your API key")
                self.model_entry.insert(0, "Replace by your model")
        except Exception as e:
            self.write(f"Error loading credentials: {e}\n")
            self.api_url_entry.insert(0, "Replace by your API URL")
            self.api_key_entry.insert(0, "Replace by your API key")
            self.model_entry.insert(0, "Replace by your model")

    def save_credentials(self, api_url, api_key, model):
        credential_file = os.path.join(self.credential_dir, "credential.json")
        credentials = {
            'api_url': api_url,
            'api_key': api_key,
            'model': model
        }
        try:
            with open(credential_file, 'w') as f:
                json.dump(credentials, f, indent=4)
            self.write("Credentials saved successfully.\n")
        except Exception as e:
            self.write(f"Error saving credentials: {e}\n")

    def redirect_warning(self, message, category, filename, lineno, file=None, line=None):
        if file is None:
            file = sys.stderr
        if file is not None and hasattr(file, 'write'):
            file.write(f"{category.__name__}: {message} ({filename}:{lineno})\n")

    def focus_window(self):
        try:
            self.root.lift()
            self.root.focus_set()
        except Exception:
            pass

    def browse_file(self):
        try:
            file_path = filedialog.askopenfilename(filetypes=[("EPUB files", "*.epub")])
            if file_path:
                self.file_entry.delete(0, tk.END)
                self.file_entry.insert(0, file_path)
        except Exception as e:
            self.write(f"Error selecting file: {e}\n")

    def clear_temp(self):
        try:
            if os.path.exists(self.temp_dir):
                shutil.rmtree(self.temp_dir)
                os.makedirs(self.temp_dir)
                self.write("Temp folder cleared successfully.\n")
            else:
                self.write("Temp folder does not exist, created new one.\n")
                os.makedirs(self.temp_dir)
        except Exception as e:
            self.write(f"Error clearing temp folder: {e}\n")

    def reveal_output(self):
        try:
            if not os.path.exists(self.output_dir):
                os.makedirs(self.output_dir)
                self.write("Output folder created.\n")
            
            if sys.platform.startswith('win'):
                os.startfile(self.output_dir)
            elif sys.platform.startswith('darwin'):
                subprocess.run(['open', self.output_dir], check=True)
            else:
                subprocess.run(['xdg-open', self.output_dir], check=True)
            self.write("Output folder opened successfully.\n")
        except Exception as e:
            self.write(f"Error opening output folder: {e}\n")

    def write(self, text):
        try:
            self.root.after(0, self._update_log, text)
        except Exception:
            if sys.stderr is not None and hasattr(sys.stderr, 'write'):
                sys.stderr.write(text)

    def _update_log(self, text):
        try:
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, f"[{time.time()}] {text}")
            self.log_text.yview(tk.END)
            self.log_text.config(state='disabled')
            if self.original_stdout is not None and hasattr(self.original_stdout, 'write'):
                self.original_stdout.write(text)
        except Exception:
            if sys.stderr is not None and hasattr(sys.stderr, 'write'):
                sys.stderr.write(text)

    def flush(self):
        if self.original_stdout is not None and hasattr(self.original_stdout, 'flush'):
            try:
                self.original_stdout.flush()
            except Exception:
                pass
        if self.original_stderr is not None and hasattr(self.original_stderr, 'flush'):
            try:
                self.original_stderr.flush()
            except Exception:
                pass

    def _check_responsiveness(self):
        try:
            self.root.after(100, self._check_responsiveness)
        except Exception:
            pass

    def translate(self):
        if self.is_translating:
            self.write("Translation already in progress. Please wait.\n")
            return
        self.is_translating = True
        self.translate_button.config(state='disabled')
        
        def run_translation():
            try:
                self.write(f"Starting translation thread at {time.time()}\n")
                epub_path = self.file_entry.get()
                platform = self.platform_var.get()
                api_url = self.api_url_entry.get()
                api_key = self.api_key_entry.get()
                model = self.model_entry.get()
                
                if not epub_path:
                    self.write("Error: Please select an EPUB file.\n")
                    return
                if not api_url or not api_key or not model:
                    self.write("Error: Please fill in all API fields.\n")
                    return
                if not platform:
                    self.write("Error: Please select a platform.\n")
                    return
                
                self.save_credentials(api_url, api_key, model)
                
                self.write("Starting EPUB processing...\n")
                extract_dir = os.path.join(self.base_dir, "extracted_epub")
                base_name_epub = os.path.basename(epub_path)
                output_epub = os.path.join(self.output_dir, base_name_epub)
                trans_epub = extract_dir
                translation_json = os.path.join(self.temp_dir, 'updated_translations.json')
                
                # Extract EPUB first
                self.write("Extracting EPUB...\n")
                try:
                    file_manager.file_manager(epub_path, extract_dir)
                except Exception as e:
                    self.write(f"Failed to extract EPUB: {str(e)}\n")
                    self.write(traceback.format_exc() + "\n")
                    return
                
                # Dynamically find the appropriate subfolder
                target_folder = 'xhtml' if platform == 'kobo' else 'OEBPS'
                input_dir = find_subfolder_path(extract_dir, target_folder)
                
                # Fallback to the other folder if the target is not found
                if not input_dir or not os.path.exists(input_dir):
                    fallback_folder = 'OEBPS' if platform == 'kobo' else 'xhtml'
                    input_dir = find_subfolder_path(extract_dir, fallback_folder)
                    if input_dir and os.path.exists(input_dir):
                        self.write(f"Warning: Expected '{target_folder}' folder not found. Using '{fallback_folder}' instead.\n")
                    else:
                        self.write(f"Error: Neither '{target_folder}' nor '{fallback_folder}' directory found in extracted_epub.\n")
                        return
                
                output_file = os.path.join(self.temp_dir, 'extracted_text.txt')
                
                self.write("Running EPUB processor...\n")
                epub_processor.ebook_processor(platform)
                self.write("Extracting text...\n")
                te = text_extractor.TextExtractor(input_dir, output_file, platform)
                te.extract_text()
                self.write("Translating content...\n")
                translator.gpt_translation(api_url=api_url, api_key=api_key, model=model, input_dir=input_dir, platform=platform, translation_json=translation_json)
                self.write("Creating translated EPUB...\n")
                file_manager.create_epub(trans_epub, output_epub)
                self.write("Translation completed successfully!\n")
                
            except Exception as e:
                self.write(f"Error during translation: {str(e)}\n")
                self.write(traceback.format_exc() + "\n")
            finally:
                self.root.after(0, lambda: self.translate_button.config(state='normal'))
                self.root.after(0, self.focus_window)
                self.root.after(0, lambda: setattr(self, 'is_translating', False))
                
        threading.Thread(target=run_translation, daemon=True).start()

def main():
    try:
        root = tk.Tk()
        app = TranslationApp(root)
        root.mainloop()
    except Exception as e:
        error_msg = f"Failed to start application: {e}\n"
        if sys.stderr is not None and hasattr(sys.stderr, 'write'):
            sys.stderr.write(error_msg)
        else:
            base_dir = get_base_path()
            log_file = os.path.join(base_dir, "error.log")
            os.makedirs(base_dir, exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{time.time()}] {error_msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()