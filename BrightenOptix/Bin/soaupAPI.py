from zeep import Client
from zeep.transports import Transport
import requests


#============================================================================================================================================#
#SOAUP csfr010 API 呼叫函式


def call_get_csfr010(wsdl_path, xml_request, timeout=10):

    session = requests.Session()

    # timeout 只會套用到讀取 WSDL；實際呼叫 SOAP 操作要靠 operation_timeout
    transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
    client = Client(wsdl=wsdl_path, transport=transport)

    response = client.service.GetCsfr010(request=xml_request)
    return response



#============================================================================================================================================#
#SOAUP asft620 API 呼叫函式
def call_get_asft620(wsdl_path, xml_request, timeout=10):

    session = requests.Session()

    transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
    client = Client(wsdl=wsdl_path, transport=transport)

    response = client.service.GetAsft620(request=xml_request)
    return response


#============================================================================================================================================#
#SOAUP asfi301 API 呼叫函式
def call_get_asfi301(wsdl_path, xml_request, timeout=10):

    session = requests.Session()

    transport = Transport(session=session, timeout=timeout, operation_timeout=timeout)
    client = Client(wsdl=wsdl_path, transport=transport)

    response = client.service.GetAsfi301(request=xml_request)
    return response
