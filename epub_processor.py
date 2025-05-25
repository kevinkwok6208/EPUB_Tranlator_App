from bs4 import BeautifulSoup
import os
from pathlib import Path
import re
import sys
from file_manager import find_subfolder_path

def get_base_path():
    """Return the base path for the application (handles PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.getcwd()

def get_file_number(filename):
    """Extract numerical part from filename for sorting."""
    match = re.search(r'(\d+)', os.path.basename(filename))
    return int(match.group(1)) if match else float('inf')

class EbookProcessor:
    def __init__(self, input_file, output_file, platform):
        self.epub_path = input_file
        self.extract_dir = output_file
        self.platform = platform
        self.base_dir = get_base_path()

    def remove_furigana(self, html_content):
        soup = BeautifulSoup(html_content, 'xml')
        for rt in soup.find_all('rt'):
            rt.decompose()
        return str(soup)

    def process_xhtml_file(self, input_file, output_file):
        if self.platform == 'kobo':
            with open(input_file, 'r', encoding='utf-8') as file:
                content = file.read()
            processed_content = self.remove_furigana(content)
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(processed_content)
        elif self.platform == 'kindle':
            with open(input_file, 'r', encoding='utf-8') as file:
                content = file.read()
            soup = BeautifulSoup(content, 'xml')
            ruby_tags = soup.find_all('ruby')
            for ruby in ruby_tags:
                kanji_parts = ruby.find_all('rb')
                kanji_text = ''.join(rb.get_text() for rb in kanji_parts)
                ruby.replace_with(kanji_text)
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(str(soup))

def ebook_processor(platform):
    base_dir = get_base_path()
    # Dynamically find the appropriate subfolder
    target_folder = 'xhtml' if platform == 'kobo' else 'OEBPS'
    xhtml_dir = find_subfolder_path(os.path.join(base_dir, "extracted_epub"), target_folder)
    if not xhtml_dir or not os.path.exists(xhtml_dir):
        print(f"Error: XHTML directory {xhtml_dir or target_folder} not found.")
        return

    # Find all XHTML files and sort by numerical order
    part_files = list(Path(xhtml_dir).glob("*.xhtml"))
    part_files = sorted(part_files, key=get_file_number)

    if not part_files:
        print(f"Warning: No XHTML files found in {xhtml_dir}.")
        return

    print(f"Found {len(part_files)} files to process.")

    # Create backup directory
    backup_dir = os.path.join(base_dir, "extracted_epub", "xhtml_backup" if platform == 'kobo' else "OEBPS_backup")
    os.makedirs(backup_dir, exist_ok=True)

    processor = EbookProcessor(None, None, platform)

    for file_path in part_files:
        rel_path = os.path.relpath(file_path, base_dir)
        try:
            backup_path = os.path.join(backup_dir, file_path.name)
            with open(file_path, 'r', encoding='utf-8') as src, open(backup_path, 'w', encoding='utf-8') as dst:
                dst.write(src.read())

            print(f"Processing file: {rel_path}")
            processor.process_xhtml_file(str(file_path), str(file_path))
            print(f"Completed processing: {rel_path} (Backup saved to {os.path.relpath(backup_path, base_dir)})")
        except PermissionError as e:
            print(f"Permission error: Unable to process {rel_path}: {str(e)}")
        except UnicodeDecodeError as e:
            print(f"Encoding error: Unable to read {rel_path}: {str(e)}")
        except Exception as e:
            print(f"Unknown error processing {rel_path}: {str(e)}")