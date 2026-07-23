from typing import List
from openpyxl import load_workbook, Workbook
from openpyxl.styles import Alignment, Font, Border, Side
from openpyxl.utils import get_column_letter
import os
import re



#============================================================================================================================================#
# 將二維陣列寫入 Excel 檔案，並根據條件設定格式

def append_2d_array_to_excel(file_path: str, data: List[List[str]]) -> None:
    # 如果檔案存在，就載入，否則新建一個
    if os.path.exists(file_path):
        wb = load_workbook(file_path)
        ws = wb.active
        ws.title = "sheet1"  # 設定工作表名稱為 sheet1
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "sheet1"

    # 取得從哪一列開始寫
    start_row = ws.max_row + 1 if ws.max_row > 1 or any(cell.value for cell in ws[1]) else 1

    # 定義三種不同的格式物件
    first_row_alignment = Alignment(wrap_text=False, vertical='center', horizontal='center') # 第一行：不換行，垂直置中，水平置中
    first_row_font = Font(bold=True) # 第一行粗體
    before_j_column_alignment = Alignment(wrap_text=False, vertical='center', horizontal='center') # I列之前：不換行，垂直置中，水平靠左
    from_j_column_alignment = Alignment(wrap_text=False, vertical='top', horizontal='left') # I列開始：自動換行，垂直偏上，水平靠左


    for row_idx, row_data in enumerate(data, start=start_row):
        for col_idx, cell_value in enumerate(row_data, start=1):
            # 清洗非法字元
            safe_value = clean_illegal_chars(str(cell_value))
            cell = ws.cell(row=row_idx, column=col_idx, value=safe_value)

            # 判斷格式套用條件
            if row_idx == 1:  # 第一行
                cell.alignment = first_row_alignment
                cell.font = first_row_font
            elif col_idx >= 9:  # I列開始（第9欄）
                cell.alignment = from_j_column_alignment
            else:  # I列之前
                cell.alignment = before_j_column_alignment

    wb.save(file_path)
    
    # 重新載入檔案以進行合併操作
    wb = load_workbook(file_path)
    ws = wb.active
    
    # 找出需要合併的欄位並進行合併
    merge_empty_cells(ws, start_row, len(data))

    add_border_to_used_cells(ws)
    wb.save(file_path)
    wb.close()



#============================================================================================================================================#
# 合併每一欄中需要合併的儲存格範圍（包含有內容和空字串的儲存格）

def merge_empty_cells(worksheet, start_row: int, data_rows: int) -> None:

    # 取得工作表的最大欄數
    max_col = worksheet.max_column
    
    # 逐欄檢查
    for col in range(1, max_col + 1):
        # 找出該欄中需要合併的範圍（包含有內容的儲存格）
        merge_ranges = find_merge_ranges(worksheet, col, start_row, start_row + data_rows - 1)
        
        # 合併找到的範圍
        for start_merge_row, end_merge_row in merge_ranges:
            if start_merge_row < end_merge_row:  # 只有當範圍超過一個儲存格時才合併
                col_letter = get_column_letter(col)
                merge_range = f"{col_letter}{start_merge_row}:{col_letter}{end_merge_row}"
                try:
                    # 保存第一個有內容的儲存格的值
                    first_content = None
                    for check_row in range(start_merge_row, end_merge_row + 1):
                        cell_value = worksheet.cell(row=check_row, column=col).value
                        if cell_value is not None and str(cell_value).strip() != "":
                            first_content = cell_value
                            break
                    
                    worksheet.merge_cells(merge_range)
                    
                    # 為合併後的儲存格設定值和對齊格式
                    merged_cell = worksheet[f"{col_letter}{start_merge_row}"]
                    if first_content is not None:
                        merged_cell.value = first_content
                    
                    if start_merge_row == 1:  # 第一行
                        merged_cell.alignment = Alignment(wrap_text=False, vertical='center', horizontal='center')
                    elif col >= 9:  # I列開始
                        merged_cell.alignment = Alignment(wrap_text=False, vertical='top', horizontal='Left')
                    else:  # I列之前
                        merged_cell.alignment = Alignment(wrap_text=False, vertical='center', horizontal='center')
                except Exception as e:
                    print(f"合併儲存格時發生錯誤 {merge_range}: {e}")


#============================================================================================================================================# 
# 找出指定欄中需要合併的範圍


def find_merge_ranges(worksheet, col: int, start_row: int, end_row: int) -> List[tuple]:

    merge_ranges = []
    
    row = start_row
    while row <= end_row:
        cell_value = worksheet.cell(row=row, column=col).value
        is_empty = cell_value is None or str(cell_value).strip() == ""
        
        if not is_empty:  # 找到有內容的儲存格
            # 檢查這個有內容的儲存格下方是否有連續的空字串
            merge_start = row
            merge_end = row
            
            # 向下搜尋連續的空字串
            for check_row in range(row + 1, end_row + 1):
                check_value = worksheet.cell(row=check_row, column=col).value
                check_is_empty = check_value is None or str(check_value).strip() == ""
                
                if check_is_empty:
                    merge_end = check_row
                else:
                    break  # 遇到非空字串就停止
            
            # 如果有找到需要合併的範圍（至少2個儲存格）
            if merge_end > merge_start:
                merge_ranges.append((merge_start, merge_end))
                row = merge_end + 1  # 跳到合併範圍之後繼續
            else:
                row += 1
        else:
            # 如果是空字串，檢查是否有連續的空字串需要合併
            empty_start = row
            empty_end = row
            
            # 向下搜尋連續的空字串
            for check_row in range(row + 1, end_row + 1):
                check_value = worksheet.cell(row=check_row, column=col).value
                check_is_empty = check_value is None or str(check_value).strip() == ""
                
                if check_is_empty:
                    empty_end = check_row
                else:
                    break
            
            # 如果有連續的空字串需要合併
            if empty_end > empty_start:
                merge_ranges.append((empty_start, empty_end))
                row = empty_end + 1
            else:
                row += 1
    
    return merge_ranges

#============================================================================================================================================# 
# 對目前所有有效儲存格加框線（包含合併儲存格左上格）

def add_border_to_used_cells(ws):
    """對目前所有有效儲存格加框線（包含合併儲存格左上格）"""
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    for row in ws.iter_rows(min_row=1, max_row=ws.max_row, min_col=1, max_col=ws.max_column):
        for cell in row:
            cell.border = thin_border

#============================================================================================================================================#
# 移除非法 Excel 字元的函式
def clean_illegal_chars(s: str) -> str:
    return re.sub(r'[\x00-\x1F]', '', s)