import os
import glob
import re
import json
from bs4 import BeautifulSoup
import sys
from file_manager import find_subfolder_path
from pathlib import Path

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

class TextExtractor:
    def __init__(self, input_dir, output_file, platform, translation_file="temp/translation_cache.json"):
        self.input_dir = input_dir
        self.output_file = output_file
        self.platform = platform
        self.base_dir = get_base_path()
        self.translation_file = os.path.join(self.base_dir, translation_file)
        self.translations = {}

    def extract_text(self):
        output_file = os.path.join(self.base_dir, self.output_file)
        input_dir = os.path.join(self.base_dir, self.input_dir)
        
        # Dynamically find the appropriate subfolder
        target_folder = 'xhtml' if self.platform == 'kobo' else 'OEBPS'
        xhtml_dir = find_subfolder_path(os.path.join(self.base_dir, "extracted_epub"), target_folder)
        if not xhtml_dir or not os.path.exists(xhtml_dir):
            print(f"Error: XHTML directory {xhtml_dir or target_folder} not found.")
            return
        
        # Find all XHTML files and sort by numerical order
        xhtml_files = list(Path(xhtml_dir).glob("*.xhtml"))
        xhtml_files = sorted(xhtml_files, key=get_file_number)

        if not xhtml_files:
            print(f"Warning: No XHTML files found in {xhtml_dir}.")
            return

        # Open the output file to write the extracted text
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as outfile:
            # Process each XHTML file
            for file_path in xhtml_files:
                # Read the XHTML file
                with open(file_path, "r", encoding="utf-8") as infile:
                    content = infile.read()
                
                # Parse the XHTML content with BeautifulSoup
                soup = BeautifulSoup(content, "lxml")
                
                # Find all <p> tags
                paragraphs = soup.find_all("p")
                for p in paragraphs:
                    if self.platform == 'kobo':
                        # Extract text from all <span> elements with class="koboSpan"
                        spans = p.find_all("span", class_="koboSpan")
                        if spans:  # Only process <p> tags with koboSpan elements
                            paragraph_text = "".join(span.get_text(strip=True) for span in spans)
                            # Write to output file, including section markers like ◇
                            if paragraph_text:
                                outfile.write(paragraph_text + "\n")
                            # Update the <p> tag's content
                            p.clear()
                            p.append(paragraph_text)
                        else:
                            # Write a blank line for empty <p> tags (e.g., <p><br/></p>)
                            outfile.write("\n")
                    elif self.platform == 'kindle':
                        # Handle <ruby> tags for furigana
                        ruby_tags = p.find_all("ruby")
                        for ruby in ruby_tags:
                            rb = ruby.find("rb")  # Kanji
                            rt = ruby.find("rt")  # Furigana
                            if rb and rt:
                                # Replace <ruby> with kanji and furigana in parentheses
                                ruby.replace_with(f"{rb.get_text(strip=True)}({rt.get_text(strip=True)})")
                            elif rb:
                                ruby.replace_with(rb.get_text(strip=True))  # Fallback to kanji only
                            
                        # Extract text from <span> elements (e.g., class_s91 for punctuation)
                        spans = p.find_all("span")
                        for span in spans:
                            span.replace_with(span.get_text(strip=True))  # Replace span with its text
                        
                        # Get the cleaned paragraph text
                        paragraph_text = p.get_text(strip=True)
                        if paragraph_text:
                            outfile.write(paragraph_text + "\n")
                        else:
                            # Write a blank line for empty <p> tags
                            outfile.write("\n")
                
                # Add an extra newline between files
                outfile.write("\n")

        print(f"Text extracted to {output_file}")

    def generate_translation_cache(self, text_file):
        """Generate translation_cache.json from a text file with empty string values, unless it already exists."""
        # Check if translation_cache.json already exists
        if os.path.exists(self.translation_file):
            print(f"Translation cache already exists at {self.translation_file}. Keeping original file.")
            return

        # Initialize translations dictionary
        self.translations = {}

        # Read the text file to extract lines
        text_file_path = os.path.join(self.base_dir, text_file)
        if not os.path.exists(text_file_path):
            print(f"Error: Text file {text_file_path} not found.")
            return

        with open(text_file_path, "r", encoding="utf-8") as infile:
            lines = infile.readlines()
            for line in lines:
                line = line.strip()
                if line:  # Only include non-empty lines
                    self.translations[line] = ""

        # Save translations to JSON file in temp/translation_cache.json
        os.makedirs(os.path.dirname(self.translation_file), exist_ok=True)
        with open(self.translation_file, "w", encoding="utf-8") as outfile:
            json.dump(self.translations, outfile, ensure_ascii=False, indent=2)

        print(f"Translation cache generated at {self.translation_file}")

if __name__ == "__main__":
    extractor = TextExtractor(input_dir="extracted_epub", output_file="output/extracted_text.txt", platform="kobo")
    extractor.extract_text()
    extractor.generate_translation_cache("input.txt")  # Assuming the provided text is in 'input.txt'