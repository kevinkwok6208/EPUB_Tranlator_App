from bs4 import BeautifulSoup
import os
from pathlib import Path
import xml
import sys

def get_base_path():
    """Return the base path for the application (handles PyInstaller bundle)."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.getcwd()

class EbookProcessor:
    def __init__(self, input_file, output_file, platform):
        self.epub_path = input_file
        self.extract_dir = output_file
        self.platform = platform
        self.base_dir = get_base_path()

    def remove_furigana(self, html_content):
        # 使用 XML 解析器來處理 XHTML
        soup = BeautifulSoup(html_content, 'xml')
        
        # 找到所有的 rt 標籤並移除，但保留 ruby 標籤內的漢字
        for rt in soup.find_all('rt'):
            rt.decompose()
        
        return str(soup)

    def process_xhtml_file(self, input_file, output_file):
        if self.platform == 'kobo':
            # 讀取原始檔案
            with open(input_file, 'r', encoding='utf-8') as file:
                content = file.read()
        
            # 處理內容
            processed_content = self.remove_furigana(content)
            
            # 寫入新檔案
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(processed_content)
        elif self.platform == 'kindle':
            # 讀取XHTML檔案
            with open(input_file, 'r', encoding='utf-8') as file:
                content = file.read()
            
            # 解析XHTML
            soup = BeautifulSoup(content, 'xml')  # 使用xml解析器來處理XHTML
            
            # 找到所有的ruby標籤
            ruby_tags = soup.find_all('ruby')
            
            # 處理每個ruby標籤
            for ruby in ruby_tags:
                # 獲取所有漢字部分（rb標籤中的內容）
                kanji_parts = ruby.find_all('rb')
                # 將漢字連接起來
                kanji_text = ''.join(rb.get_text() for rb in kanji_parts)
                # 用漢字替換整個ruby標籤
                ruby.replace_with(kanji_text)
            
            # 保存處理後的檔案
            with open(output_file, 'w', encoding='utf-8') as file:
                file.write(str(soup))

def ebook_processor(platform):
    base_dir = get_base_path()
    if platform == 'kobo':
        # 定義XHTML檔案所在的目錄
        xhtml_dir = os.path.join(base_dir, "extracted_epub", "item", "xhtml")
        
        # 確認目錄存在
        if not os.path.exists(xhtml_dir):
            print(f"錯誤: XHTML目錄 {xhtml_dir} 不存在")
            return
        
        # 使用glob模式尋找所有符合模式的檔案
        part_files = list(Path(xhtml_dir).glob("p-[0-9]*.xhtml"))
        
        if not part_files:
            print("警告: 沒有找到任何符合 p-[0-9]*.xhtml 模式的檔案")
            return
        
        print(f"找到 {len(part_files)} 個檔案需要處理")
        
        # 創建備份目錄
        backup_dir = os.path.join(base_dir, "extracted_epub", "item", "xhtml_backup")
        os.makedirs(backup_dir, exist_ok=True)
        
        # 初始化EbookProcessor
        processor = EbookProcessor(None, None, platform)  # 參數在process_xhtml_file中直接使用
        
        # 處理每個檔案
        for file_path in part_files:
            rel_path = os.path.relpath(file_path, base_dir)
            
            try:
                # 創建備份
                backup_path = os.path.join(backup_dir, file_path.name)
                with open(file_path, 'r', encoding='utf-8') as src, open(backup_path, 'w', encoding='utf-8') as dst:
                    dst.write(src.read())
                
                print(f"處理檔案: {rel_path}")
                processor.process_xhtml_file(str(file_path), str(file_path))  # 直接覆蓋原檔案
                print(f"完成處理: {rel_path} (備份已保存至 {os.path.relpath(backup_path, base_dir)})")
                
            except PermissionError as e:
                print(f"權限錯誤: 無法處理 {rel_path}: {str(e)}")
            except UnicodeDecodeError as e:
                print(f"編碼錯誤: 無法讀取 {rel_path}: {str(e)}")
            except Exception as e:
                print(f"處理 {rel_path} 時發生未知錯誤: {str(e)}")

    elif platform == 'kindle':
        # 定義XHTML檔案所在的目錄
        xhtml_dir = os.path.join(base_dir, "extracted_epub", "OEBPS")
        
        # 使用glob模式尋找所有符合模式的檔案
        part_files = list(Path(xhtml_dir).glob("part*.xhtml"))
        
        print(f"找到 {len(part_files)} 個檔案需要處理")
        
        processor = EbookProcessor(None, None, platform)
        # 處理每個檔案
        for file_path in part_files:
            # 獲取相對路徑用於顯示
            rel_path = os.path.relpath(file_path, base_dir)
            
            # 檢查檔案是否存在 (雖然glob已經確保檔案存在，但保留此檢查以保持一致性)
            if os.path.exists(file_path):
                try:
                    print(f"處理檔案: {rel_path}")
                    processor.process_xhtml_file(str(file_path), str(file_path))  # 直接覆蓋原檔案
                    print(f"完成處理: {rel_path}")
                except Exception as e:
                    print(f"處理 {rel_path} 時發生錯誤: {str(e)}")
            else:
                print(f"找不到檔案: {rel_path}")