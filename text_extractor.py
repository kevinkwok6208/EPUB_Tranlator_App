import os
import glob
import re
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
    def __init__(self, input_dir, output_file, platform):
        self.input_dir = input_dir
        self.output_file = output_file
        self.platform = platform
        self.base_dir = get_base_path()

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