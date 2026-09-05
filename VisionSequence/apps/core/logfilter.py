"""日誌遮罩：影像與 SSE 的 URL 帶 ?token=／api_key=（EventSource 與 <img> 不能帶標頭），
uvicorn 的 access log 會把整條 query string 寫進 service.log——遮掉，日誌才能交給別人看。"""

from __future__ import annotations

import logging
import re

_SECRET = re.compile(r"(token|api_key|password|secret)=([^&\s\"']+)", re.IGNORECASE)


def redact(text: str) -> str:
    return _SECRET.sub(lambda m: f"{m.group(1)}=***", text)


class RedactSecrets(logging.Filter):
    """掛在 uvicorn.access（與任何會印 URL 的 logger）上：msg 與字串型 args 一併遮罩。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: (redact(v) if isinstance(v, str) else v) for k, v in record.args.items()}
        return True
