import epub_processor 
import file_manager
import text_extractor
import translator
import os
def main():
    # Paramete for file_manager.py
    os.makedirs("output", exist_ok=True)
    os.makedirs("temp", exist_ok=True)

    # Epub platform
    platform ='kindle'
    
    epub_path = "cut.epub"
    extract_dir = "extracted_epub"
    
    base_name_epub=os.path.basename(epub_path)
    output_epub=f'output/{base_name_epub}'
    
    trans_epub='extracted_epub'
    translation_json='temp/updated_translations.json'
    # Parameters for epub_processor.py
    # input_dir in different platforms
    if platform == 'kobo':
        input_dir = 'extracted_epub/item/xhtml'
    elif platform == 'kindle':
        input_dir = 'extracted_epub/OEBPS'
        
    output_file='temp/extracted_text.txt'

    file_manager.file_manager(epub_path, extract_dir)
    epub_processor.ebook_processor(platform)
    te=text_extractor.TextExtractor(input_dir, output_file,platform)
    te.extract_text()
    
    # Parameters for translator.py
    api_url='#Replace by your api url '
    api_key = 'enter you api key'
    model='enter you model'
    translator.gpt_translation(api_url=api_url,api_key=api_key,model=model,
                               input_dir=input_dir,platform=platform,
                               translation_json=translation_json)
    file_manager.create_epub(trans_epub,output_epub)

if __name__ == "__main__":
    main()