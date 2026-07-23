import soaupAPI
import xlsxWrite


#  wsdl的URL，測試用
wsdl = 'http://192.168.1.15/web/ws/r/aws_ttsrv2_toptest?wsdl'

# 建立 payload，根據 WSDL 定義，GetCsfr010 要求一個 request 字串
xml_request = """
<Request>
    <Access>
        <Authentication user="A0482" password="tim590330"/>
        <Connection application="TIPTOP" source="192.168.1.15"/>
        <Organization name="BTOX"/>
        <Locale language="zh_tw"/>
    </Access>
    <RequestContent>
        <Parameter>
            <Record>
                <Field name="sfb01" value="A518-2504230020"/>
            </Record>
        </Parameter>
    </RequestContent>
</Request>
"""


#============================================================================================================================================#
# 呼叫 GetCsfr010 SOAP API 並將結果寫入 Excel 檔案

def LV_csfr010(wsdl: str, xml_request: str, xlsfilename: str ,timeout):

    # 呼叫 SOAP API
    soap_response = soaupAPI.call_get_csfr010(wsdl, xml_request, timeout)

    # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)
    
    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)
    
    # 將結果寫入 Excel 檔案
    xlsxWrite.tuple_to_excel(field_map_tuple, xlsfilename)

    return field_map_traditional_tuple , soap_response_traditional


#============================================================================================================================================#
# 呼叫 Getasft620 SOAP API

def LV_asft620(wsdl: str, xml_request: str, timeout):
    # 呼叫 SOAP API
    soap_response = soaupAPI.call_get_asft620(wsdl, xml_request,timeout)

    # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)
    
    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)

    return field_map_traditional_tuple , soap_response_traditional


#============================================================================================================================================#
# 呼叫 Asfi301 SOAP API

def LV_asfi301(wsdl: str, xml_request: str, timeout):
    # 呼叫 SOAP API
    soap_response = soaupAPI.call_get_asfi301(wsdl, xml_request,timeout)

    # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)
    
    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)

    return field_map_traditional_tuple , soap_response_traditional



#============================================================================================================================================#
# 呼叫 模擬 GetCsfr010 SOAP API 並將結果寫入 Excel 檔案

def LV_csfr010_simulate(filePath: str, xlsfilename: str):
    # 讀取模擬的 SOAP 回應
    soap_response = xlsxWrite.read_txt_file(filePath)

    # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)

    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)
    
    # 將結果寫入 Excel 檔案
    xlsxWrite.tuple_to_excel(field_map_tuple, xlsfilename)

    return field_map_traditional_tuple , soap_response_traditional


#============================================================================================================================================#
# 呼叫 模擬 Getasft620 SOAP API

def LV_asft620_simulate(filePath: str):
    # 讀取模擬的 SOAP 回應
    soap_response = xlsxWrite.read_txt_file(filePath)

     # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)
    
    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)

    return field_map_traditional_tuple , soap_response_traditional


#============================================================================================================================================#
# 呼叫 模擬 Asfi301 SOAP API

def LV_asfi301_simulate(filePath: str):
    # 讀取模擬的 SOAP 回應
    soap_response = xlsxWrite.read_txt_file(filePath)

     # 將模擬的 SOAP 回應轉換為繁體中文
    soap_response_traditional = xlsxWrite.translate_to_traditional_chinese_string(soap_response)
    
    # 解析 SOAP 回應
    field_map_tuple = xlsxWrite.parse_soap_field_map(soap_response)
    
    # 將結果轉換為繁體中文
    field_map_traditional_tuple = xlsxWrite.translate_to_traditional_chinese_tuple(field_map_tuple)

    return field_map_traditional_tuple , soap_response_traditional