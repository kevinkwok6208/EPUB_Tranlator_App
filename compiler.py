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

def get_base_path():
    """Return the base path for the application (handles PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        # Running as a PyInstaller executable
        return os.path.dirname(sys.executable)
    else:
        # Running as a Python script
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
        # Only write to original_stream if it exists and has a write method
        if self.original_stream is not None and hasattr(self.original_stream, 'write'):
            try:
                self.original_stream.write(text)
            except Exception:
                pass  # Silently ignore errors in original_stream
        self.buffer.write(text)

    def _update_text(self):
        if self.text_buffer:
            combined_text = ''.join(self.text_buffer)
            self.text_buffer = []  # Clear buffer
            try:
                self.text_widget.config(state='normal')
                self.text_widget.insert(tk.END, combined_text)
                self.text_widget.yview(tk.END)
                self.text_widget.config(state='disabled')
            except Exception:
                pass  # Prevent crashes if text_widget is unavailable
        # Reschedule the update
        self._schedule_update()

    def _schedule_update(self):
        try:
            self.text_widget.after(self.update_interval, self._update_text)
        except Exception:
            pass  # Prevent crashes if text_widget is destroyed

    def flush(self):
        self.buffer.flush()
        if self.original_stream is not None and hasattr(self.original_stream, 'flush'):
            try:
                self.original_stream.flush()
            except Exception:
                pass  # Silently ignore flush errors

class TranslationApp:
    def __init__(self, root):
        self.root = root
        self.root.title("EPUB Translator")
        self.root.geometry("600x500")
        self.root.attributes('-topmost', False)
        self.is_translating = False  # Flag to track translation state
        
        # Base directory for the application
        self.base_dir = get_base_path()
        self.output_dir = os.path.join(self.base_dir, "output")
        self.temp_dir = os.path.join(self.base_dir, "temp")
        self.credential_dir = os.path.join(self.base_dir, "credential")
        
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
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.credential_dir, exist_ok=True)
        
        # Redirect stdout and stderr
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        sys.stdout = StreamRedirector(self.log_text, sys.stdout)
        sys.stderr = StreamRedirector(self.log_text, sys.stderr)
        
        # Redirect warnings to stderr
        warnings.showwarning = self.redirect_warning
        
        # Start responsiveness check
        self.root.after(1000, self._check_responsiveness)

    def load_credentials(self):
        """Load credentials from credential.json if it exists."""
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
        """Save credentials to credential.json."""
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
        """Redirect warnings to stderr."""
        if file is None:
            file = sys.stderr
        if file is not None and hasattr(file, 'write'):
            file.write(f"{category.__name__}: {message} ({filename}:{lineno})\n")

    def focus_window(self):
        """Bring the window to the front."""
        try:
            self.root.lift()
            self.root.focus_set()
        except Exception:
            pass  # Prevent crashes if window is unavailable

    def browse_file(self):
        """Open file dialog to select EPUB file."""
        try:
            file_path = filedialog.askopenfilename(filetypes=[("EPUB files", "*.epub")])
            if file_path:
                self.file_entry.delete(0, tk.END)
                self.file_entry.insert(0, file_path)
        except Exception as e:
            self.write(f"Error selecting file: {e}\n")

    def clear_temp(self):
        """Clear all files in the temp folder."""
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
        """Open the output folder in the system's default file explorer."""
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
        """Write text to the log widget in the main thread."""
        try:
            self.root.after(0, self._update_log, text)
        except Exception:
            # Fallback to stderr if GUI is unavailable
            if sys.stderr is not None and hasattr(sys.stderr, 'write'):
                sys.stderr.write(text)

    def _update_log(self, text):
        """Update log widget with timestamped text."""
        try:
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, f"[{time.time()}] {text}")
            self.log_text.yview(tk.END)
            self.log_text.config(state='disabled')
            if self.original_stdout is not None and hasattr(self.original_stdout, 'write'):
                self.original_stdout.write(text)
        except Exception:
            # Fallback to stderr if GUI is unavailable
            if sys.stderr is not None and hasattr(sys.stderr, 'write'):
                sys.stderr.write(text)

    def flush(self):
        """Flush the output streams."""
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
        """Periodically check if the event loop is responsive."""
        try:
            self.root.after(100, self._check_responsiveness)
        except Exception:
            pass  # Prevent crashes if root is destroyed

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
                extract_dir = os.path.join(self.base_dir, "extracted_epub")
                base_name_epub = os.path.basename(epub_path)
                output_epub = os.path.join(self.output_dir, base_name_epub)
                trans_epub = extract_dir
                translation_json = os.path.join(self.temp_dir, 'updated_translations.json')
                
                # Set input_dir based on platform
                if platform == 'kobo':
                    input_dir = os.path.join(extract_dir, 'item', 'xhtml')
                elif platform == 'kindle':
                    input_dir = os.path.join(extract_dir, 'OEBPS')
                else:
                    self.write("Error: Invalid platform selected.\n")
                    return
                
                output_file = os.path.join(self.temp_dir, 'extracted_text.txt')
                
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
    try:
        root = tk.Tk()
        app = TranslationApp(root)
        root.mainloop()
    except Exception as e:
        # Log to stderr or a file if GUI fails to initialize
        error_msg = f"Failed to start application: {e}\n"
        if sys.stderr is not None and hasattr(sys.stderr, 'write'):
            sys.stderr.write(error_msg)
        else:
            # Fallback to file logging
            base_dir = get_base_path()
            log_file = os.path.join(base_dir, "error.log")
            os.makedirs(base_dir, exist_ok=True)
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(f"[{time.time()}] {error_msg}")
        sys.exit(1)

if __name__ == "__main__":
    main()