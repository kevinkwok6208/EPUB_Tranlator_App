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
        self.original_stream.write(text)
        self.buffer.write(text)

    def _update_text(self):
        if self.text_buffer:
            combined_text = ''.join(self.text_buffer)
            self.text_buffer = []  # Clear buffer
            self.text_widget.config(state='normal')
            self.text_widget.insert(tk.END, combined_text)
            self.text_widget.yview(tk.END)
            self.text_widget.config(state='disabled')
        # Reschedule the update
        self._schedule_update()

    def _schedule_update(self):
        self.text_widget.after(self.update_interval, self._update_text)

    def flush(self):
        self.buffer.flush()
        self.original_stream.flush()

class TranslationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB Translator")
        self.root.geometry("600x500")
        self.root.attributes('-topmost', False)
        self.is_translating = False  # Flag to track translation state
        
        # Create main frame
        self.main_frame = ttk.Frame(self.root, padding="10")
        self.main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # File selection
        ttk.Label(self.main_frame, text="EPUB File:").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.file_entry = ttk.Entry(self.main_frame, width=50)
        self.file_entry.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5)
        ttk.Button(self.main_frame, text="Browse", command=self.browse_file).grid(row=0, column=2, padx=5)
        
        # Platform selection
        ttk.Label(self.main_frame, text="Platform:").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.platform_var = tk.StringVar(value="kindle")
        self.platform_menu = ttk.Combobox(self.main_frame, textvariable=self.platform_var, values=["kindle", "kobo"], state="readonly", width=47)
        self.platform_menu.grid(row=1, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # API URL
        ttk.Label(self.main_frame, text="API URL:").grid(row=2, column=0, sticky=tk.W, pady=5)
        self.api_url_entry = ttk.Entry(self.main_frame, width=50)
        self.api_url_entry.grid(row=2, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # API Key
        ttk.Label(self.main_frame, text="API Key:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.api_key_entry = ttk.Entry(self.main_frame, width=50)
        self.api_key_entry.grid(row=3, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Model selection
        ttk.Label(self.main_frame, text="Model:").grid(row=4, column=0, sticky=tk.W, pady=5)
        self.model_entry = ttk.Entry(self.main_frame, width=50)
        self.model_entry.grid(row=4, column=1, columnspan=2, sticky=(tk.W, tk.E), pady=5)
        
        # Load saved credentials
        self.load_credentials()
        
        # Buttons
        self.translate_button = ttk.Button(self.main_frame, text="Translate", command=self.translate)
        self.translate_button.grid(row=5, column=1, pady=10)
        ttk.Button(self.main_frame, text="Start New Book", command=self.clear_temp).grid(row=5, column=2, pady=10)
        ttk.Button(self.main_frame, text="Focus Window", command=self.focus_window).grid(row=5, column=0, pady=10)
        ttk.Button(self.main_frame, text="Reveal Output", command=self.reveal_output).grid(row=6, column=1, pady=10)
        
        # Log display
        ttk.Label(self.main_frame, text="Log:").grid(row=7, column=0, sticky=tk.W, pady=5)
        self.log_text = scrolledtext.ScrolledText(self.main_frame, width=60, height=15, wrap=tk.WORD)
        self.log_text.grid(row=8, column=0, columnspan=3, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.log_text.config(state='disabled')
        
        # Configure grid weights
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(8, weight=1)
        
        # Create output and temp directories
        os.makedirs("output", exist_ok=True)
        os.makedirs("temp", exist_ok=True)
        os.makedirs("credential", exist_ok=True)
        
        # Redirect stdout and stderr
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = StreamRedirector(self.log_text, self.original_stdout)
        sys.stderr = StreamRedirector(self.log_text, self.original_stderr)
        
        # Redirect warnings to stderr
        warnings.showwarning = self.redirect_warning
        
        # Start responsiveness check
        self.root.after(1000, self._check_responsiveness)

    def load_credentials(self):
        """Load credentials from credential.json if it exists."""
        credential_file = os.path.join("credential", "credential.json")
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
        """Save credentials to credential.json."""
        credential_file = os.path.join("credential", "credential.json")
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
        """Redirect warnings to stderr."""
        if file is None:
            file = sys.stderr
        file.write(f"{category.__name__}: {message} ({filename}:{lineno})\n")
        
    def focus_window(self):
        """Bring the window to the front."""
        self.root.lift()
        self.root.focus_set()
        
    def browse_file(self):
        """Open file dialog to select EPUB file."""
        file_path = filedialog.askopenfilename(filetypes=[("EPUB files", "*.epub")])
        if file_path:
            self.file_entry.delete(0, tk.END)
            self.file_entry.insert(0, file_path)
            
    def clear_temp(self):
        """Clear all files in the temp folder."""
        temp_dir = "temp"
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                os.makedirs(temp_dir)
                self.write("Temp folder cleared successfully.\n")
            else:
                self.write("Temp folder does not exist, created new one.\n")
                os.makedirs(temp_dir)
        except Exception as e:
            self.write(f"Error clearing temp folder: {e}\n")
            
    def reveal_output(self):
        """Open the output folder in the system's default file explorer."""
        output_dir = os.path.abspath("output")
        try:
            if not os.path.exists(output_dir):
                os.makedirs(output_dir)
                self.write("Output folder created.\n")
            
            if sys.platform.startswith('win'):
                os.startfile(output_dir)
            elif sys.platform.startswith('darwin'):
                subprocess.run(['open', output_dir], check=True)
            else:
                subprocess.run(['xdg-open', output_dir], check=True)
            self.write("Output folder opened successfully.\n")
        except Exception as e:
            self.write(f"Error opening output folder: {e}\n")
            
    def write(self, text):
        """Write text to the log widget in the main thread."""
        self.root.after(0, self._update_log, text)
        
    def _update_log(self, text):
        """Update log widget with timestamped text."""
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, f"[{time.time()}] {text}")
        self.log_text.yview(tk.END)
        self.log_text.config(state='disabled')
        self.original_stdout.write(text)
        
    def flush(self):
        """Flush the output streams."""
        self.original_stdout.flush()
        self.original_stderr.flush()
        
    def _check_responsiveness(self):
        """Periodically check if the event loop is responsive."""
        self.root.after(100, self._check_responsiveness)
        
    def translate(self):
        """Run the translation process in a background thread."""
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
                
                # Save credentials
                self.save_credentials(api_url, api_key, model)
                
                self.write("Starting EPUB processing...\n")
                extract_dir = "extracted_epub"
                base_name_epub = os.path.basename(epub_path)
                output_epub = f'output/{base_name_epub}'
                trans_epub = 'extracted_epub'
                translation_json = 'temp/updated_translations.json'
                
                # Set input_dir based on platform
                if platform == 'kobo':
                    input_dir = 'extracted_epub/item/xhtml'
                elif platform == 'kindle':
                    input_dir = 'extracted_epub/OEBPS'
                else:
                    self.write("Error: Invalid platform selected.\n")
                    return
                
                output_file = 'temp/extracted_text.txt'
                
                self.write("Extracting EPUB...\n")
                file_manager.file_manager(epub_path, extract_dir)
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
                self.write(f"Error during translation: {e}\n")
            finally:
                self.root.after(0, lambda: self.translate_button.config(state='normal'))
                self.root.after(0, self.focus_window)
                self.root.after(0, lambda: setattr(self, 'is_translating', False))
                
        threading.Thread(target=run_translation, daemon=True).start()

def main():
    root = tk.Tk()
    app = TranslationApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()