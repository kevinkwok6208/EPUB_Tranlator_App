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
    """Handles text analysis for Japanese and English character detection"""
    
    def __init__(self):
        self.japanese_pattern = re.compile(
            '[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF\uFF00-\uFFEF]'
        )
        self.japanese_specific_pattern = re.compile(r'[ぁ-んァ-ン]')
        self.english_pattern = re.compile(r'[a-zA-Z]')  # Basic English detection
        self.punctuation_only_pattern = re.compile(r'^[「」…―\s]+$')  # Detects punctuation-only strings

    def is_japanese(self, text: str) -> bool:
        """Check if text contains Japanese characters"""
        return bool(self.japanese_pattern.search(text))

    def is_english(self, text: str) -> bool:
        """Check if text contains English characters"""
        return bool(self.english_pattern.search(text))

    def is_untranslated(self, ch_text: str) -> bool:
        """Check if text contains Japanese-specific characters (for JSON validation)"""
        return bool(self.japanese_specific_pattern.search(ch_text))

    def is_punctuation_only(self, text: str) -> bool:
        """Check if text consists only of punctuation or whitespace"""
        return bool(self.punctuation_only_pattern.match(text))

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

    def batch_translate_for_json(self, texts: List[str], cache: TranslationCache, batch_size: int = 5) -> Dict[str, str]:
        """Translate a batch of texts to Traditional Chinese, expecting newline-separated response."""
        translations = {}
        if not texts:
            return translations

        # Check cache first
        uncached_texts = [text for text in texts if not cache.get(text)]
        if not uncached_texts:
            return {text: cache.get(text) for text in texts}

        prompt = (
            "Translate the following texts to **Traditional Chinese (繁體中文)**. "
            "Each translation must be separated by a newline (\\n). "
            "Maintain the exact order of the input texts.\n\n"
            "### Rules:\n"
            "1. Use **exclusively Traditional Chinese characters** (e.g., 「圖」 not 「图」).\n"
            "2. Never use Simplified Chinese characters.\n"
            "3. Preserve original formatting, punctuation, and line breaks within each text.\n"
            "4. Localize names/titles appropriately for Traditional Chinese audiences.\n"
            "5. If the text is already in Chinese, verify it's Traditional Chinese or convert it.\n\n"
            "Input texts (in order):\n"
        )

        for idx, text in enumerate(uncached_texts, 1):
            prompt += f"{idx}. {text}\n"

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional translator specialized in translating from any language to **Traditional Chinese**.\n"
                            "### Key Rules:\n"
                            "1. **Always** output in Traditional Chinese (繁體中文).\n"
                            "2. Reject any Simplified Chinese characters.\n"
                            "3. Maintain original formatting, including spaces and punctuation within each text.\n"
                            "4. Localize terms appropriately (e.g., 'software' → '軟體', not '软件').\n"
                            "5. Output translations in the exact order of input, separated by newlines (\\n).\n"
                            "6. If the text is already Chinese, verify it's Traditional or convert it."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.3
            )

            # Split the response by newlines, accounting for potential extra newlines
            translation_text = response.choices[0].message.content
            translated_lines = [line.strip() for line in translation_text.split('\n') if line.strip()]
            
            # Remove numbered prefixes (e.g., "1. ", "2. ") if present
            cleaned_translations = []
            for line in translated_lines:
                if re.match(r'^\d+\.', line):
                    cleaned_translations.append(re.sub(r'^\d+\.\s*', '', line))
                else:
                    cleaned_translations.append(line)

            # Ensure the number of translations matches the input
            if len(cleaned_translations) != len(uncached_texts):
                print(f"Warning: Expected {len(uncached_texts)} translations, got {len(cleaned_translations)}. Using original texts for mismatches.")
                for text in uncached_texts:
                    translations[text] = text  # Fallback to original text
            else:
                for original, translated in zip(uncached_texts, cleaned_translations):
                    translations[original] = translated
                    cache.set(original, translated)

            # Add cached translations for texts that were already cached
            for text in texts:
                if text not in translations:
                    translations[text] = cache.get(text)

            return translations
        except Exception as e:
            print(f"Batch translation error: {e}")
            return {text: text for text in texts}  # Fallback to original texts

    def translate_single(self, text: str, cache: TranslationCache) -> str:
        """Translate a single text to Traditional Chinese."""
        # Check cache first
        cached_translation = cache.get(text)
        if cached_translation:
            return cached_translation

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional translator specialized in translating from any language to **Traditional Chinese (繁體中文)**. "
                            "Your translations must **exclusively use Traditional Chinese characters** (e.g., 「繁體中文」, not 「简体中文」).\n\n"
                            "### Rules:\n"
                            "1. Preserve original formatting, punctuation, and line breaks.\n"
                            "2. Localize names/titles appropriately for Traditional Chinese audiences.\n"
                            "3. **Never** use Simplified Chinese characters.\n"
                            "4. If the input is already in Chinese, confirm it's Traditional Chinese or convert it."
                        )
                    },
                    {
                        "role": "user",
                        "content": f"Translate the following text to **Traditional Chinese (繁體中文)**:\n{text}\n\n"
                                   "**Reminder**: Use **only** Traditional Chinese characters and maintain original formatting."
                    }
                ],
                temperature=0.3
            )
            translation = response.choices[0].message.content.strip()
            cache.set(text, translation)
            return translation
        except Exception as e:
            print(f"Translation error for '{text}': {e}")
            return text

class JsonProcessor:
    """Handles JSON file operations and translation updates"""
    
    def __init__(self, cache_files: List[str], output_file: str = "temp/updated_translations.json"):
        self.base_dir = get_base_path()
        self.cache_files = [os.path.join(self.base_dir, f) for f in cache_files]
        self.output_file = os.path.join(self.base_dir, output_file)
        self.text_analyzer = TextAnalyzer()

    def load_json(self, cache_file: str) -> Dict[str, str]:
        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            print(f"Cache file {cache_file} not found. Starting with empty cache.")
            return {}
        except json.JSONDecodeError:
            print(f"Error decoding JSON in {cache_file}. Starting with empty cache.")
            return {}

    def save_json(self, json_data: Dict[str, str]):
        os.makedirs(os.path.dirname(self.output_file), exist_ok=True)
        with open(self.output_file, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)

    def find_untranslated(self, json_data: Dict[str, str], check_japanese: bool = False) -> List[str]:
        untranslated = []
        for jp_text, ch_text in json_data.items():
            if not jp_text:  # Skip empty keys
                continue
            if check_japanese:
                # After batch translation: Check for empty values or Japanese characters in translated text
                if ch_text == "" or self.text_analyzer.is_japanese(ch_text):
                    if not self.text_analyzer.is_punctuation_only(jp_text):  # Exclude punctuation-only strings
                        untranslated.append(jp_text)
                        print(f"Detected untranslated: '{jp_text}' (Reason: {'Empty value' if ch_text == '' else 'Contains Japanese characters'})")
                    else:
                        print(f"Skipping punctuation-only text: '{jp_text}'")
                else:
                    print(f"Skipping valid translation: '{jp_text}' -> '{ch_text}'")
            else:
                # Initial check: Only look for empty values
                if ch_text == "":  # Untranslated if value is empty string
                    if not self.text_analyzer.is_punctuation_only(jp_text):  # Exclude punctuation-only strings
                        untranslated.append(jp_text)
                        print(f"Detected untranslated: '{jp_text}'")
                    else:
                        print(f"Skipping punctuation-only text: '{jp_text}'")
                else:
                    print(f"Skipping already translated: '{jp_text}' -> '{ch_text}'")
        return untranslated

    def process(self, translator: Translator, batch_size: int = 5):
        for cache_file in self.cache_files:
            print(f"Processing cache file: {cache_file}")
            json_data = self.load_json(cache_file)
            untranslated = self.find_untranslated(json_data)

            if not untranslated:
                print("All entries are properly translated or skipped!")
                self.save_json(json_data)  # Save to output even if no translations needed
                continue

            print(f"Found {len(untranslated)} untranslated entries.")
            updated_json = json_data.copy()
            cache = TranslationCache(cache_file)
            total_untranslated = len(untranslated)

            # Step 1: Batch translation
            for i in range(0, len(untranslated), batch_size):
                batch = untranslated[i:i + batch_size]
                print(f"Batch translating batch {i // batch_size + 1} of {((len(untranslated) - 1) // batch_size + 1)} "
                      f"({len(batch)} entries, {((i + len(batch)) / total_untranslated * 100):.2f}% complete)")
                translations = translator.batch_translate_for_json(batch, cache, batch_size)
                for text, translation in translations.items():
                    updated_json[text] = translation

            # Step 2: Check for remaining untranslated entries (empty or containing Japanese)
            remaining_untranslated = self.find_untranslated(updated_json, check_japanese=True)
            if remaining_untranslated:
                print(f"Found {len(remaining_untranslated)} entries still untranslated after batch translation. Switching to line-by-line translation.")
                for i, text in enumerate(remaining_untranslated, 1):
                    print(f"Translating entry {i} of {len(remaining_untranslated)} ({(i / len(remaining_untranslated) * 100):.2f}% complete)")
                    translation = translator.translate_single(text, cache)
                    updated_json[text] = translation

            self.save_json(updated_json)
            print(f"Updated {len(untranslated)} translations and saved to '{self.output_file}'")

class TranslationManager:
    """Coordinates JSON translation processes"""
    
    def __init__(self, api_url: str, api_key: str, model: str, cache_files: List[str]):
        self.translator = Translator(api_url, api_key, model)
        self.json_processor = JsonProcessor(cache_files)
        self.text_analyzer = TextAnalyzer()

    def process_all(self):
        """Run JSON processing"""
        print("Starting JSON translation update...")
        self.json_processor.process(self.translator, batch_size=20) # Change here if you want change the number of lines per batch.

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
    cache_files = [
        os.path.join(base_dir, 'temp', 'translation_cache.json'),
        os.path.join(base_dir, 'temp', 'updated_translations.json')
    ]
    input_dir = os.path.join(base_dir, input_dir)
    translation_json = os.path.join(base_dir, translation_json)

    # Ensure temp directory exists
    os.makedirs(os.path.join(base_dir, 'temp'), exist_ok=True)

    # Initialize and run the manager
    manager = TranslationManager(api_url, api_key, model, cache_files)
    manager.process_all()

    xhtml_updator = Update_Xhtml_Manager(input_dir=input_dir, translations_file=translation_json, platform=platform)
    xhtml_updator.run()