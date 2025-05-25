from openai import OpenAI
import os
import re
import json
import glob
from typing import List, Dict
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

class TextAnalyzer:
    """Handles text analysis for Japanese character detection"""
    
    def __init__(self):
        self.japanese_pattern = re.compile(
            '[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]'
        )
        self.japanese_specific_pattern = re.compile(r'[ぁ-んァ-ン]')

    def is_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters"""
        return bool(self.japanese_pattern.search(text))

    def is_untranslated(self, ch_text: str) -> bool:
        """Check if text contains Japanese-specific characters (for JSON validation)"""
        return bool(self.japanese_specific_pattern.search(ch_text))

class TranslationCache:
    """Manages caching of translations"""
    
    def __init__(self, cache_file: str = "temp/translation_cache.json"):
        self.base_dir = get_base_path()
        self.cache_file = os.path.join(self.base_dir, cache_file)
        self.cache = self._load_cache()

    def _load_cache(self) -> dict:
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save_cache(self):
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        with open(self.cache_file, 'w', encoding='utf-8') as f:
            json.dump(self.cache, f, ensure_ascii=False, indent=2)

    def get(self, text: str) -> str:
        return self.cache.get(text)

    def set(self, text: str, translation: str):
        self.cache[text] = translation
        self.save_cache()

class Translator:
    """Handles translation operations using OpenAI API"""
    
    def __init__(self, api_url: str, api_key: str, model: str):
        self.client = OpenAI(base_url=api_url, api_key=api_key)
        self.model = model

    def batch_translate_for_file(self, texts: List[str], cache: TranslationCache) -> List[str]:
        """Translate multiple texts for file processing"""
        if not texts:
            return []

        combined_text = "\n===SPLIT===\n".join(texts)
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional translator specialized in Detected Language to **Traditional Chinese (繁體中文)** translation. "
                            "Your translations must **exclusively use Traditional Chinese characters** (e.g., 「繁體中文」, not 「简体中文」).\n\n"
                            "### Rules:\n"
                            "1. Preserve original formatting, punctuation, and line breaks.\n"
                            "2. Localize names/titles appropriately for Traditional Chinese audiences.\n"
                            "3. **Never** use Simplified Chinese characters.\n"
                            "4. Separate translations with ===SPLIT===.\n\n"
                            "If the input is already in Chinese, confirm it's Traditional Chinese or convert it."
                        )
                    },
                    {
                        "role": "user", 
                        "content": f"Translate the following Detected Language text to **Traditional Chinese (繁體中文)**:\n{combined_text}\n\n"
                                   "**Reminder**: Use **only** Traditional Chinese characters and maintain original formatting."
                    }
                ],
                temperature=0.3
            )
            
            translations = response.choices[0].message.content.split("===SPLIT===")
            translations = [t.strip() for t in translations]
            for original, translated in zip(texts, translations):
                cache.set(original, translated)
            return translations
        except Exception as e:
            print(f"Translation error: {e}")
            return texts

    def batch_translate_for_json(self, texts: List[str], batch_size: int = 5) -> Dict[str, str]:
        """Translate texts for JSON processing"""
        translations = {}
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            prompt = (
                "Translate the following Detected Language texts to **Traditional Chinese (繁體中文)**:\n\n"
                "===SPLIT===\n\n"
                "**Important Requirements**:\n"
                "- Use **exclusively Traditional Chinese characters** (e.g., 「圖」 not 「图」).\n"
                "- Never simplify characters (e.g., 「體」 not 「体」).\n"
                "- Preserve original formatting, punctuation, and line breaks.\n"
                "- Separate translations with ===SPLIT===."
            )

            for idx, text in enumerate(batch, 1):
                prompt += f"{idx}. {text}\n"

            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are a professional translator specialized in Detected Language to **Traditional Chinese**.\n"
                                "### Key Rules:\n"
                                "1. **Always** output in Traditional Chinese (繁體中文).\n"
                                "2. Reject any Simplified Chinese characters.\n"
                                "3. Maintain original formatting, including spaces and line breaks.\n"
                                "4. Localize terms appropriately (e.g., 'ソフトウェア' → '軟體', not '软件').\n"
                                "5. If the text is already Chinese, verify it's Traditional or convert it."
                            )
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )

                translation_text = response.choices[0].message.content
                lines = translation_text.split('\n')
                for line in lines:
                    if re.match(r'^\d+\.', line):
                        parts = line.split('.', 1)
                        if len(parts) > 1:
                            idx = int(parts[0]) - 1
                            if idx < len(batch):
                                translations[batch[idx]] = parts[1].strip()
            except Exception as e:
                print(f"Error in batch translation: {e}")
                continue
        return translations

class FileProcessor:
    """Manages text file processing and translation"""
    
    def __init__(self, input_path: str, output_path: str, batch_size: int = 50):
        self.base_dir = get_base_path()
        self.input_path = os.path.join(self.base_dir, input_path)
        self.output_path = os.path.join(self.base_dir, output_path)
        self.batch_size = batch_size
        self.cache = TranslationCache()
        self.text_analyzer = TextAnalyzer()

    def read_paragraphs(self) -> List[str]:
        with open(self.input_path, 'r', encoding='utf-8') as file:
            return [line.strip() for line in file.read().splitlines() if line.strip()]

    def write_paragraphs(self, paragraphs: List[str]):
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)
        with open(self.output_path, 'w', encoding='utf-8') as file:
            file.write('\n'.join(paragraphs))

    def process(self, translator: Translator):
        try:
            paragraphs = self.read_paragraphs()
            translated_paragraphs = []
            current_batch = []
            total_paragraphs = len(paragraphs)

            for i, paragraph in enumerate(paragraphs, 1):
                if i % 50 == 0:
                    print(f"Processing paragraph {i} of {total_paragraphs} ({(i/total_paragraphs)*100:.2f}%)")

                cached_translation = self.cache.get(paragraph)
                if cached_translation:
                    translated_paragraphs.append(cached_translation)
                    continue

                if self.text_analyzer.is_japanese(paragraph):
                    current_batch.append(paragraph)
                else:
                    translated_paragraphs.append(paragraph)
                    continue

                if len(current_batch) >= self.batch_size:
                    print(f"Translating batch of {len(current_batch)} paragraphs...")
                    translations = translator.batch_translate_for_file(current_batch, self.cache)
                    translated_paragraphs.extend(translations)
                    current_batch = []

            if current_batch:
                print(f"Translating final batch of {len(current_batch)} paragraphs...")
                translations = translator.batch_translate_for_file(current_batch, self.cache)
                translated_paragraphs.extend(translations)

            self.write_paragraphs(translated_paragraphs)
            print(f"Translation completed. Output saved to: {self.output_path}")
            print(f"Total paragraphs processed: {len(translated_paragraphs)}")
        except Exception as e:
            print(f"Error processing file: {e}")

class JsonProcessor:
    """Handles JSON file operations and translation updates"""
    
    def __init__(self, cache_files: List[str], output_file: str = "temp/updated_translations.json"):
        self.base_dir = get_base_path()
        self.cache_files = [os.path.join(self.base_dir, f) for f in cache_files]
        self.output_file = os.path.join(self.base_dir, output_file)
        self.text_analyzer = TextAnalyzer()

    def load_json(self, cache_file: str) -> Dict[str, str]:
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def save_json(self, json_data: Dict[str, str]):
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

    def find_untranslated(self, json_data: Dict[str, str]) -> List[str]:
        untranslated = []
        for jp_text, ch_text in json_data.items():
            if not jp_text or not ch_text:
                continue
            if self.text_analyzer.is_untranslated(ch_text) or jp_text == ch_text:
                untranslated.append(jp_text)
        return untranslated

    def update_json(self, original_json: Dict[str, str], new_translations: Dict[str, str]) -> Dict[str, str]:
        updated_json = original_json.copy()
        for jp_text, ch_translation in new_translations.items():
            if jp_text in updated_json:
                updated_json[jp_text] = ch_translation
        return updated_json

    def process(self, translator: Translator):
        for cache_file in self.cache_files:
            print(f"Processing cache file: {cache_file}")
            json_data = self.load_json(cache_file)
            untranslated = self.find_untranslated(json_data)

            if not untranslated:
                print("All entries are properly translated!")
                continue

            print(f"Found {len(untranslated)} untranslated entries.")
            new_translations = translator.batch_translate_for_json(untranslated)
            updated_json = self.update_json(json_data, new_translations)
            self.save_json(updated_json)
            print(f"Updated {len(new_translations)} translations and saved to '{self.output_file}'")

class TranslationManager:
    """Coordinates text file and JSON translation processes"""
    
    def __init__(self, api_url: str, api_key: str, model: str, input_file: str, output_file: str, cache_files: List[str]):
        self.translator = Translator(api_url, api_key, model)
        self.file_processor = FileProcessor(input_file, output_file)
        self.json_processor = JsonProcessor(cache_files)

    def process_all(self):
        """Run both file and JSON processing"""
        print("Starting text file translation...")
        self.file_processor.process(self.translator)
        print("\nStarting JSON translation update...")
        self.json_processor.process(self.translator)

class Update_Xhtml_Manager:
    def __init__(self, input_dir="", translations_file="", platform=''):
        """
        Initialize the EbookTranslator with paths to input directory and translations file.
        
        Args:
            input_dir (str): Directory containing XHTML files
            translations_file (str): Path to translations JSON file
        """
        self.base_dir = get_base_path()
        self.input_dir = os.path.join(self.base_dir, input_dir)
        self.translations_file = os.path.join(self.base_dir, translations_file)
        self.platform = platform
        self.translations = {}
        self.xhtml_files = []
    
    def load_translations(self):
        """Load translations from JSON file."""
        try:
            with open(self.translations_file, "r", encoding="utf-8") as f:
                self.translations = json.load(f)
            return True
        except Exception as e:
            print(f"Error loading translations: {e}")
            return False
    
    def get_xhtml_files(self):
        """Get all XHTML files and sort them numerically."""
        target_folder = 'xhtml' if self.platform == 'kobo' else 'OEBPS'
        xhtml_dir = find_subfolder_path(os.path.join(self.base_dir, "extracted_epub"), target_folder)
        if not xhtml_dir or not os.path.exists(xhtml_dir):
            print(f"Error: XHTML directory {xhtml_dir or target_folder} not found.")
            return 0
        
        self.xhtml_files = sorted(
            glob.glob(os.path.join(xhtml_dir, "*.xhtml")), 
            key=get_file_number
        )
        return len(self.xhtml_files)
    
    def update_xhtml_files(self):
        """Process each XHTML file and update with translations."""
        if not self.xhtml_files:
            self.get_xhtml_files()
        
        updated_count = 0
        for file_path in self.xhtml_files:
            if self._update_single_file(file_path):
                updated_count += 1
        
        return updated_count
    
    def _update_single_file(self, file_path):
        """Update a single XHTML file with translations."""
        try:
            # Read the XHTML file
            with open(file_path, "r", encoding="utf-8") as infile:
                content = infile.read()
            
            # Parse the XHTML content with BeautifulSoup
            soup = BeautifulSoup(content, "lxml")
            
            # Find all <p> tags
            paragraphs = soup.find_all("p")
            changes_made = False
            
            for p in paragraphs:
                # Skip <p> tags with <br/> or structural markers like ◇
                if p.find("br") or p.get_text(strip=True) == "◇":
                    continue
                
                # Extract the text content of the <p> tag
                paragraph_text = p.get_text(strip=True)
                
                # Check if the text has a translation
                if paragraph_text in self.translations:
                    # Clear the <p> tag's contents
                    p.clear()
                    # Append the translated text
                    p.append(self.translations[paragraph_text])
                    changes_made = True
            
            # Write the modified XHTML back to the original file if changes were made
            if changes_made:
                with open(file_path, "w", encoding="utf-8") as outfile:
                    outfile.write(str(soup))
                return True
            
            return False
        except Exception as e:
            print(f"Error updating file {file_path}: {e}")
            return False
    
    def run(self):
        """Run the entire translation process."""
        if not self.load_translations():
            return "Failed to load translations."
        
        file_count = self.get_xhtml_files()
        if file_count == 0:
            return "No XHTML files found."
        
        updated_count = self.update_xhtml_files()
        return f"Updated {updated_count} of {file_count} XHTML files with translations from {self.translations_file}"
        
def gpt_translation(api_url, api_key, model, platform, input_dir, translation_json):
    # Configuration
    base_dir = get_base_path()
    input_file = os.path.join(base_dir, 'temp', 'extracted_text.txt')
    output_file = os.path.join(base_dir, 'temp', 'output.txt')
    cache_files = [
        os.path.join(base_dir, 'temp', 'translation_cache.json'),
        os.path.join(base_dir, 'temp', 'updated_translations.json')
    ]
    input_dir = os.path.join(base_dir, input_dir)
    translation_json = os.path.join(base_dir, translation_json)

    # Initialize and run the manager
    manager = TranslationManager(api_url, api_key, model, input_file, output_file, cache_files)
    manager.process_all()

    xhtml_updator = Update_Xhtml_Manager(input_dir=input_dir, translations_file=translation_json, platform=platform)
    xhtml_updator.run()