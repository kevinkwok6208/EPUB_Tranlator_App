import os
import re
import json
from bs4 import BeautifulSoup
import sys
from tools.file_manager import find_subfolder_path
from pathlib import Path
import xml.etree.ElementTree as ET

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

    def find_xhtml_files(self):
        """
        Locate the folder containing XHTML files and return a list of XHTML file paths in spine order.
        Returns a tuple: (xhtml_folder, xhtml_files) or (None, None) if not found.
        """
        # Step 1: Parse container.xml to find the .opf file
        container_path = os.path.join(self.base_dir, "extracted_epub", "META-INF", "container.xml")
        if not os.path.exists(container_path):
            print("Error: container.xml not found.")
            return None, None

        try:
            tree = ET.parse(container_path)
            root = tree.getroot()
            namespace = {'ns': 'urn:oasis:names:tc:opendocument:xmlns:container'}
            opf_path = root.find('.//ns:rootfile[@media-type="application/oebps-package+xml"]', namespace).attrib['full-path']
        except (ET.ParseError, AttributeError) as e:
            print(f"Error parsing container.xml: {e}")
            return None, None

        # Step 2: Parse the .opf file to find XHTML files
        opf_full_path = os.path.join(self.base_dir, "extracted_epub", opf_path)
        if not os.path.exists(opf_full_path):
            print(f"Error: .opf file not found at {opf_full_path}")
            return None, None

        try:
            tree = ET.parse(opf_full_path)
            root = tree.getroot()
            namespace = {'opf': 'http://www.idpf.org/2007/opf'}

            # Get manifest (map id to href)
            manifest = {}
            for item in root.findall('.//opf:manifest/opf:item', namespace):
                if item.attrib.get('media-type') == 'application/xhtml+xml':
                    manifest[item.attrib['id']] = item.attrib['href']

            # Get spine (reading order)
            spine = [itemref.attrib['idref'] for itemref in root.findall('.//opf:spine/opf:itemref', namespace)]

            # Build list of XHTML file paths in spine order
            xhtml_files = []
            content_dir = os.path.dirname(opf_path)  # e.g., 'OEBPS'
            xhtml_folder = None
            for idref in spine:
                if idref in manifest:
                    xhtml_path = manifest[idref]
                    full_path = Path(self.base_dir) / "extracted_epub" / content_dir / xhtml_path
                    if full_path.exists():
                        xhtml_files.append(full_path)
                        if xhtml_folder is None:
                            xhtml_folder = str(full_path.parent)  # Set folder from first valid file
                    else:
                        print(f"Warning: XHTML file not found at {full_path}")

            if not xhtml_files:
                # Fallback to searching for XHTML files if spine parsing fails
                print("Warning: No valid XHTML files found in manifest. Attempting fallback search.")
                xhtml_dir = (find_subfolder_path(os.path.join(self.base_dir, "extracted_epub"), "Text") or
                             find_subfolder_path(os.path.join(self.base_dir, "extracted_epub"), "xhtml") or
                             find_subfolder_path(os.path.join(self.base_dir, "extracted_epub"), content_dir))
                if xhtml_dir:
                    xhtml_files = sorted(Path(xhtml_dir).glob("*.xhtml"), key=get_file_number)
                    xhtml_folder = xhtml_dir
                else:
                    print("Error: No XHTML files found in fallback search.")
                    return None, None

            return xhtml_folder, xhtml_files
        except (ET.ParseError, AttributeError) as e:
            print(f"Error parsing .opf file: {e}")
            return None, None

    def extract_text(self):
        output_file = os.path.join(self.base_dir, self.output_file)
        input_dir = os.path.join(self.base_dir, self.input_dir)

        # Find XHTML folder and files using EPUB metadata
        xhtml_dir, xhtml_files = self.find_xhtml_files()
        if not xhtml_dir or not xhtml_files:
            print(f"Error: XHTML directory or files not found.")
            return

        print(f"Found XHTML directory: {xhtml_dir}")
        print(f"Found {len(xhtml_files)} XHTML files.")

        # Open the output file to write the extracted text
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as outfile:
            # Process each XHTML file in spine order
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