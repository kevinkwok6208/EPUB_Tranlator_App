import zipfile
import os
import shutil
from pathlib import Path
import sys
import re

def get_base_path():
    """Return the base path for the application (handles PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.getcwd()

def find_subfolder_path(root_folder, target_folder):
    """Search for a subfolder within root_folder and return its path."""
    for root, dirs, _ in os.walk(root_folder):
        if target_folder in dirs:
            return os.path.join(root, target_folder)
    return None

class FileManager:
    def __init__(self, epub_path, extract_dir):
        self.epub_path = epub_path
        self.extract_dir = extract_dir
        self.base_dir = get_base_path()
        
    def file_unzip(self):
        # Ensure extract_dir is absolute
        extract_dir = os.path.join(self.base_dir, self.extract_dir)
        
        # Delete the directory if it already exists
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir)
            print(f"Removed existing directory: {extract_dir}")
        # Create the directory if it doesn't exist
        if not os.path.exists(extract_dir):
            os.makedirs(extract_dir)

        # Extract the epub
        with zipfile.ZipFile(self.epub_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
            
        print(f"EPUB extracted to {extract_dir}")

        # List the extracted files
        for root, dirs, files in os.walk(extract_dir):
            level = root.replace(extract_dir, '').count(os.sep)
            indent = ' ' * 4 * level
            print(f"{indent}{os.path.basename(root)}/")
            sub_indent = ' ' * 4 * (level + 1)
            for file in files:
                print(f"{sub_indent}{file}")

def file_manager(epub_path, extract_dir):
    fm = FileManager(epub_path, extract_dir)
    fm.file_unzip()

def create_epub(trans_epub, output_epub):
    """
    Convert a folder with EPUB contents into a valid EPUB file.
    
    Args:
        trans_epub (str): Path to the folder containing EPUB contents.
        output_epub (str): Path for the output .epub file.
    """
    base_dir = get_base_path()
    trans_epub = os.path.join(base_dir, trans_epub)
    output_epub = os.path.join(base_dir, output_epub)
    
    epub_folder = Path(trans_epub)
    output_epub = Path(output_epub)
    
    # Verify required files
    if not (epub_folder / "mimetype").exists():
        raise FileNotFoundError("Missing 'mimetype' file in EPUB folder.")
    if not (epub_folder / "META-INF" / "container.xml").exists():
        raise FileNotFoundError("Missing 'META-INF/container.xml' in EPUB folder.")
    
    # Create EPUB (ZIP) file
    with zipfile.ZipFile(output_epub, "w", compression=zipfile.ZIP_DEFLATED) as epub:
        # Write mimetype file first, uncompressed
        mimetype_path = epub_folder / "mimetype"
        epub.write(mimetype_path, "mimetype", compress_type=zipfile.ZIP_STORED)
        
        # Walk through the folder and add all other files
        for root, dirs, files in os.walk(epub_folder):
            for file in files:
                file_path = Path(root) / file
                # Skip mimetype as it's already added
                if file_path == mimetype_path:
                    continue
                # Calculate the relative path for the ZIP
                arcname = file_path.relative_to(epub_folder)
                # Add file to ZIP with compression
                epub.write(file_path, arcname, compress_type=zipfile.ZIP_DEFLATED)
    
    print(f"EPUB created successfully: {output_epub}")