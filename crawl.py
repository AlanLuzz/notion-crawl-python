# ====== 設定區域 ======
# Notion API Token (請填入你的 API Token)
NOTION_TOKEN = ""

# Notion Database ID (請填入你要爬取的資料庫 ID)
DATABASE_ID = ""

# 輸出資料夾名稱(./)
OUTPUT_FOLDER = "notion_data"
# ====================

from notion_client import Client
import os
from tqdm import tqdm
import time

# 初始化 Notion client
notion = Client(auth=NOTION_TOKEN)

class NotionStructure:
    def __init__(self):
        self.root_pages = {}  # 儲存根頁面結構
        self.total_pages = 0  # 總頁面數
        self.file_pages = []  # 需要產生檔案的頁面列表

def process_rich_text(rich_text):
    """處理富文字，轉換為標準 Markdown 格式"""
    result = []
    for text in rich_text:
        content = text.get('plain_text', '')
        annotations = text.get('annotations', {})
        
        # 使用標準 Markdown 語法
        if annotations.get('bold'): content = f"**{content}**"
        if annotations.get('italic'): content = f"*{content}*"
        if annotations.get('code'): content = f"`{content}`"
        if text.get('href'): content = f"[{content}]({text['href']})"
        
        result.append(content)
    
    return ''.join(result)

def analyze_block_structure(block_id, indent=0, structure=None, order_counter=None, number_counters=None, pbar=None):
    """遞迴分析區塊結構，依照深度處理"""
    if structure is None:
        structure = {
            'blocks': [],
            'images': [],
            'toggles': []
        }
    if order_counter is None:
        order_counter = {'count': 0}
    if number_counters is None:
        number_counters = {'current': 0, 'last_heading': None}
    
    try:
        blocks = notion.blocks.children.list(block_id=block_id)
        total_blocks = len(blocks.get('results', []))
        
        for i, block in enumerate(blocks.get('results', [])):
            if pbar:
                pbar.update(1)
                time.sleep(0.01)  # 讓進度條更新更平滑
                
            block_type = block.get('type')
            current_order = order_counter['count']
            order_counter['count'] += 1
            
            # 處理表格
            if block_type == 'table':
                table_rows = notion.blocks.children.list(block_id=block['id'])
                rows = []
                for row in table_rows.get('results', []):
                    if row.get('type') == 'table_row':
                        cells = row['table_row']['cells']
                        row_content = []
                        for cell in cells:
                            cell_text = process_rich_text(cell) if cell else ''
                            row_content.append(cell_text.strip())
                        rows.append(row_content)
                
                if rows:
                    # 建立標準 Markdown 表格
                    header = '| ' + ' | '.join(rows[0]) + ' |'
                    separator = '|' + '|'.join(['---'] * len(rows[0])) + '|'
                    data_rows = ['| ' + ' | '.join(row) + ' |' for row in rows[1:]]
                    table_content = '\n'.join([header, separator] + data_rows)
                    
                    structure['blocks'].append({
                        'type': 'table',
                        'text': table_content,
                        'order': current_order
                    })
            
            elif block_type == 'image':
                image_url = block['image'].get('file', {}).get('url') or block['image'].get('external', {}).get('url')
                if image_url:
                    structure['blocks'].append({
                        'type': 'image',
                        'text': f"![圖片]({image_url})",
                        'order': current_order
                    })
            
            elif block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3', 
                              'bulleted_list_item', 'numbered_list_item']:
                text = block[block_type].get('rich_text', [])
                if text:
                    content = process_rich_text(text)
                    
                    if block_type.startswith('heading_'):
                        level = int(block_type[-1])
                        if level == 1:
                            content = f"# {content}"
                        elif level == 2:
                            content = f"## {content}"
                        elif level == 3:
                            content = f"### {content}"
                        number_counters['current'] = 0
                    
                    elif block_type == 'bulleted_list_item':
                        content = f"- {content}"
                    elif block_type == 'numbered_list_item':
                        number_counters['current'] += 1
                        content = f"{number_counters['current']}. {content}"
                    
                    structure['blocks'].append({
                        'type': block_type,
                        'text': content,
                        'order': current_order
                    })
            
            if block.get('has_children'):
                analyze_block_structure(block['id'], indent + 1, structure, order_counter, number_counters, pbar)
                
    except Exception as e:
        print(f"\n處理區塊失敗 (ID: {block_id}): {e}")
    
    return structure

def get_page_title(page_id):
    """取得頁面標題"""
    try:
        page = notion.pages.retrieve(page_id=page_id)
        if 'properties' in page and 'title' in page['properties']:
            title = page['properties']['title']['title']
            if title:
                return title[0]['plain_text']
        return f'頁面_{page_id}'
    except Exception as e:
        print(f"\n取得頁面標題失敗（ID: {page_id}）：{str(e)}")
        return f'頁面_{page_id}'

def get_database_pages(database_id):
    """取得資料庫中的所有頁面"""
    try:
        pages = []
        has_more = True
        next_cursor = None
        page_count = 0
        
        print("\n開始查詢資料庫...")
        while has_more:
            response = notion.databases.query(
                database_id=database_id,
                start_cursor=next_cursor
            )
            
            if not response or 'results' not in response:
                print(f"錯誤：無法取得資料庫（ID: {database_id}）的回應")
                return None
            
            current_batch = response['results']
            pages.extend(current_batch)
            page_count += len(current_batch)
            print(f"\r目前找到 {page_count} 個頁面", end="")
            
            has_more = response.get('has_more', False)
            next_cursor = response.get('next_cursor')
            time.sleep(0.1)  # 讓進度顯示更平滑
        
        print(f"\n查詢完成！總共找到 {page_count} 個頁面")
        return pages
    except Exception as e:
        print(f"查詢資料庫時發生錯誤（ID: {database_id}）：{str(e)}")
        return None

def save_content(content, file_name):
    """儲存內容到 Markdown 文件"""
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        file_name = "".join(c for c in file_name.replace('/', '_').replace('\\', '_') 
                           if c.isalnum() or c in (' ', '-', '_'))
        
        with open(f"{OUTPUT_FOLDER}/{file_name}.md", "w", encoding="utf-8") as f:
            for line in content:
                f.write(line + '\n')
            
    except Exception as e:
        print(f"\n儲存檔案失敗：{str(e)}")

def get_page_structure(page_id, parent_id=None, structure=None, depth=0, pbar=None):
    """遞迴取得頁面結構"""
    if structure is None:
        structure = NotionStructure()
    
    try:
        page = notion.pages.retrieve(page_id=page_id)
        page_title = get_page_title(page_id)
        is_file_page = page_title.endswith("(1)") or (depth == 2)
        
        if pbar and depth <= 1:  # 只在主要頁面顯示進度
            current = len(structure.root_pages) + 1
            print(f"\r正在分析頁面結構 ({current}/{pbar.total}): {page_title}", end="")
        
        page_info = {
            'title': page_title.replace(" (1)", ""),
            'children': [],
            'id': page_id,
            'is_file_page': is_file_page
        }
        
        if is_file_page:
            structure.file_pages.append(page_info)
        
        structure.total_pages += 1
        
        blocks = notion.blocks.children.list(block_id=page_id)
        for block in blocks.get('results', []):
            if block.get('type') == 'child_page':
                next_depth = 2 if depth == 1 else depth + 1
                child_info = get_page_structure(block['id'], page_id, structure, next_depth, pbar)
                if child_info:
                    page_info['children'].append(child_info)
        
        if depth <= 1:  # 只在完成主要頁面時更新進度條
            pbar.update(1)
        
        return page_info
        
    except Exception as e:
        print(f"\n取得頁面結構失敗（ID: {page_id}）：{str(e)}")
        return None

def generate_files(structure):
    """產生所有檔案"""
    try:
        os.makedirs(OUTPUT_FOLDER, exist_ok=True)
        pages_to_process = structure.file_pages
        total_files = len(pages_to_process)
        
        if total_files == 0:
            print("\n沒有找到需要處理的檔案")
            return
        
        print(f"\n開始處理，總共 {total_files} 個檔案")
        
        # 使用單一進度條顯示整體進度
        with tqdm(total=total_files, desc="處理進度") as pbar:
            for i, page in enumerate(pages_to_process, 1):
                print(f"\r正在處理 ({i}/{total_files}): {page['title']}", end="")
                structure = analyze_block_structure(page['id'])
                if structure:
                    all_blocks = [(item['order'], item['text']) for item in structure['blocks']]
                    all_blocks.sort(key=lambda x: x[0])
                    content = [block[1] for block in all_blocks]
                    save_content(content, page['title'])
                pbar.update(1)
                time.sleep(0.1)  # 讓進度顯示更平滑
                
    except Exception as e:
        print(f"\n產生檔案時發生錯誤：{str(e)}")

def main():
    try:
        structure = NotionStructure()
        
        # 查詢資料庫
        pages = get_database_pages(DATABASE_ID)
        
        if not pages:
            print("錯誤：找不到資料庫中的頁面或無法查詢資料庫")
            return
        
        total_pages = len(pages)
        print(f"\n開始分析頁面結構，總共 {total_pages} 個頁面...")
        
        # 分析頁面結構
        with tqdm(total=total_pages, desc="分析進度") as pbar:
            for page in pages:
                try:
                    page_structure = get_page_structure(page['id'], None, structure, 1, pbar)
                    if page_structure:
                        structure.root_pages[page['id']] = page_structure
                except Exception as e:
                    print(f"\n取得頁面結構失敗（ID: {page['id']}）：{str(e)}")
        
        # 產生檔案
        generate_files(structure)
        print("\n程式執行完成！")
        
    except Exception as e:
        print(f"\n程式執行失敗：{str(e)}")

if __name__ == "__main__":
    main()
