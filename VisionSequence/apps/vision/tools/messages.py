"""工具與引擎的執行訊息：英文句子照舊，另外帶一個代碼與參數，前端依介面語言組句子（PM-REVIEW-R2 L-4 第 1 點）。

用法：

    Result(message=Msg.of("template_match.found", "{n} matches, best {score:.3f}", n=3, score=0.975))
    raise ToolError(Msg.of("tolerance_judge.not_number", "The input is not a number: {raw!r}", raw=raw))

- 英文＝`template.format(**args)`，所以把既有的 f-string 改成 Msg 不會改變任何訊息文字（API、TCP、操作紀錄、bench 都照舊）。
- 參數依樣板裡的格式規格與轉換先變成顯示用字串（`{score:.3f}` → "0.975"、`{raw!r}` → repr），前端不必處理數字格式。
- 代碼與樣板一律寫成字面常數：`tests/test_tool_messages.py` 靜態掃描所有 `Msg.of("代碼", "樣板", ...)`，確認
  `frontend/src/i18n/locales/toolMessages.zh-Hant.ts`／`.zh-Hans.ts` 都有這個代碼、中文的佔位符不超出樣板、同一代碼只對一個樣板。
- 樣板欄位只用簡單名稱（`{name}`，不要 `{a[b]}`／`{a.b}`）；不要把 Msg 和別的字串相加（相加後就變回普通字串、代碼消失）。
"""

from __future__ import annotations

import string
from typing import Any

_FORMATTER = string.Formatter()


def fields(template: str) -> list[str]:
    """樣板裡的欄位名稱（依出現順序、不重複）。"""
    out: list[str] = []
    for _literal, field, _spec, _conversion in _FORMATTER.parse(template):
        if field is not None and field not in out:
            out.append(field)
    return out


def _display(template: str, args: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for _literal, field, spec, conversion in _FORMATTER.parse(template):
        if field is None or field in out:
            continue
        value = args[field]
        if conversion == "r":
            value = repr(value)
        elif conversion == "s":
            value = str(value)
        elif conversion == "a":
            value = ascii(value)
        out[field] = format(value, spec) if spec else str(value)
    return out


class Msg(str):
    """帶代碼與顯示參數的訊息字串（本身就是那句英文）。"""

    code: str
    args: dict[str, str]

    def __new__(cls, text: str, code: str = "", args: dict[str, str] | None = None):
        obj = super().__new__(cls, text)
        obj.code = code
        obj.args = dict(args or {})
        return obj

    @classmethod
    def of(cls, code: str, template: str, **args: Any) -> "Msg":
        return cls(template.format(**args), code, _display(template, args))

    def __reduce__(self):
        return (Msg, (str(self), self.code, self.args))

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def parts(message: Any) -> tuple[str, dict[str, str]]:
    """(代碼, 參數)；普通字串回 ("", {})。"""
    if isinstance(message, Msg) and message.code:
        return message.code, dict(message.args)
    return "", {}
