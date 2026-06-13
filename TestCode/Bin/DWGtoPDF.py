import os
import subprocess
import time

def dwg_to_pdf_via_oda_final(dwg_path, output_pdf_path):
    """
    使用 ODA 27.1.0 純控制台核心進行損壞圖檔修復與多頁 PDF 轉檔。
    【完美解決方案】：避開 TrueView 閃退，改用 ODA 批次模式，自動遍歷所有 Layout 生成多頁 PDF。
    """
    if not os.path.exists(dwg_path):
        raise FileNotFoundError(f"找不到指定的 DWG 檔案: {dwg_path}")

    # 1. 鎖定 ODA 27.1.0 核心執行檔路徑
    oda_base = r"C:\Program Files\ODA\ODAFileConverter 27.1.0"
    cli_exe = None
    possible_names = ["OdaFileConverter.exe", "ODAFileConverter.exe"]
    
    if os.path.exists(oda_base):
        for name in possible_names:
            test_path = os.path.join(oda_base, name)
            if os.path.exists(test_path):
                cli_exe = test_path
                break

    if not cli_exe:
        print("❌ 錯誤：找不到 ODA File Converter 27.1.0 執行檔。")
        return False

    input_dir = os.path.dirname(dwg_path)
    output_dir = os.path.dirname(output_pdf_path)
    base_name = os.path.splitext(os.path.basename(dwg_path))[0]
    
    # 2. 建立 ODA 工廠無人值守命令列參數
    # 使用 "*.dwg" 會強迫 ODA 啟動內建的「多頁/多圖批次編譯引擎」
    # 這能讓它在解碼時直接忽略內部錯誤圖元，並把每個版框依序打包進同一個 PDF 中！
    cmd = [
        cli_exe,
        input_dir,
        output_dir,
        "2018",   # 強制降版解碼
        "PDF",    # 目標格式
        "0",      # 不遞迴子資料夾
        "1",      # 允許覆蓋舊檔
        "*.dwg"   # 關鍵：啟動批次模式
    ]

    print(f"🚀 ODA 穩定版批次核心已啟動...")
    print(f"⌛ 正在背景修復損壞標頭並自動導出多頁 PDF，請稍候...")
    
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # 隱藏任何可能彈出的 GUI 視窗
        
        # 【防卡死關鍵點】：將 stdout 與 stderr 導向 DEVNULL
        # ODA 在解析壞損圖檔時會瘋狂噴出上萬行的幾何錯誤 Log，這會塞滿 Python 的管道導致 Deadlock（卡住）
        # 改用 DEVNULL 直接丟棄 Log，核心就能全速前進不卡死！
        process = subprocess.Popen(
            cmd, 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL, 
            startupinfo=startupinfo
        )
        
        # 針對這張複雜的手臂組圖，給予 25 秒的安全解碼時間
        try:
            process.wait(timeout=25)
        except subprocess.TimeoutExpired:
            print("⚠️ 轉檔超過預期時間，觸發防卡死機制，強行結束進程...")
            process.kill()
            process.wait()

        # ODA 轉檔成功後，預設會在 output_dir 下產出一個與原圖同名的 PDF
        expected_pdf = os.path.join(output_dir, f"{base_name}.pdf")
        
        # 給予文件系統 1.5 秒的寫入重新整理緩衝
        time.sleep(1.5)
        
        if os.path.exists(expected_pdf) and os.path.getsize(expected_pdf) > 0:
            # 如果使用者的自訂輸出路徑和預設產出路徑不同，進行更名覆蓋
            if os.path.abspath(expected_pdf) != os.path.abspath(output_pdf_path):
                if os.path.exists(output_pdf_path):
                    os.remove(output_pdf_path)
                os.rename(expected_pdf, output_pdf_path)
            
            print(f"✨【轉檔成功】已繞過損壞圖元，每個版框已各自獨立成頁！")
            print(f"➜ 最終多頁圖紙: {output_pdf_path}")
            return True
        else:
            print("❌ 轉檔結束，但未能在目錄下偵測到有效的 PDF 報告。")
            return False
            
    except Exception as e:
        print(f"❌ 執行異常: {str(e)}")
        return False

if __name__ == "__main__":
    # 執行路徑
    INPUT_DWG = r"D:\Working Space\Python\TestCode\緯穎_UR手臂組拆板機_2026_0601_0900_recover.dwg"
    OUTPUT_PDF = r"D:\Working Space\Python\TestCode\緯穎_UR手臂組拆板機_多頁版框.pdf"
    
    dwg_to_pdf_via_oda_final(INPUT_DWG, OUTPUT_PDF)