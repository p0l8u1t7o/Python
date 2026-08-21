"""The UI glossary, checked for the mistakes TypeScript cannot see.

TypeScript already guarantees every entry has all three languages — the type
requires it, so a half-filled entry does not compile. What it cannot tell is
whether the strings are *right*: a zh-Hans definition pasted from zh-Hant type
checks perfectly and is still wrong, and that is precisely the failure mode
that makes a simplified-Chinese UI read as an afterthought.

So these tests read the source and look for the things a compiler will not:
copies, Taiwanese technical vocabulary in the mainland text, and ids referenced
from a page but missing from the table.
"""

from __future__ import annotations

import re
from pathlib import Path

from django.test import SimpleTestCase

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "src"
GLOSSARY_FILE = FRONTEND / "lib" / "glossary.ts"

#: Terms that belong in the glossary but have no label in the console yet -
#: they appear in the device protocol and the API rather than on a page. Listed
#: explicitly so an entry that is simply unused gets noticed instead of quietly
#: accumulating.
REFERENCE_ONLY = {
    "coincidentPeak",
    "coverage",
    "demand",
    "downlink",
    "includeInBalance",
    "peakShaving",
    "qos",
    "retained",
    "touArbitrage",
}

#: Traditional-only technical vocabulary. Each of these has a different
#: standard word in mainland usage, so finding one in zh-Hans means the text
#: was converted character by character instead of actually translated.
TAIWAN_ONLY = {
    "韌體": "固件",
    "軟體": "软件",
    "程式": "程序",
    "資料": "数据",
    "網路": "网络",
    "訊息": "消息",
    "伺服器": "服务器",
    "佇列": "队列",
    "快取": "缓存",
    "逾時": "超时",
    "元件": "组件",
    "效能": "性能",
    "太陽光電": "光伏",
    "時間電價": "分时电价",
    "迴圈": "循环",
    "位元組": "字节",
}


def _source() -> str:
    return GLOSSARY_FILE.read_text(encoding="utf-8")


def _entries() -> dict[str, str]:
    """Split the table into `id -> raw entry body`."""
    source = _source()
    start = source.index("export const GLOSSARY = {")
    body = source[start:]
    matches = list(re.finditer(r"^  (\w+): \{$", body, re.M))
    entries: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        entries[match.group(1)] = body[match.start() : end]
    return entries


def _field(block: str, field: str, language: str) -> str:
    """Pull one language out of one field of an entry."""
    section = re.search(rf"^    {field}: \{{(.*?)^    \}},", block, re.S | re.M)
    if section is None:
        return ""
    key = language if language == "en" else f"'{language}'"
    value = re.search(rf"{re.escape(key)}:\s*\n?\s*'((?:[^'\\]|\\.)*)'", section.group(1))
    return value.group(1) if value else ""


def _ids_from_lookup_tables(text: str) -> set[str]:
    """Ids reached indirectly, through a `GlossaryId`-typed table.

    Some pages map a status or a flag onto a term rather than writing
    `<Term id="…">` literally. Those uses are just as real, so a scan that only
    looked for the literal form would report half the table as dead.
    """
    found: set[str] = set()
    for match in re.finditer(r":[^=\n]*GlossaryId[^=]*=\s*([\[{])", text):
        opener = match.group(1)
        closer = "]" if opener == "[" else "}"
        depth = 0
        start = match.end() - 1
        for index in range(start, len(text)):
            if text[index] == opener:
                depth += 1
            elif text[index] == closer:
                depth -= 1
                if depth == 0:
                    found.update(re.findall(r"'(\w+)'", text[start : index + 1]))
                    break
    return found


class GlossaryStructureTests(SimpleTestCase):
    def test_the_table_is_not_empty(self):
        self.assertGreater(len(_entries()), 30, "術語表看起來沒有被正確解析")

    def test_every_entry_has_all_three_languages(self):
        missing: list[str] = []
        for term, block in _entries().items():
            for field in ("label", "definition"):
                for language in ("en", "zh-Hant", "zh-Hans"):
                    if not _field(block, field, language).strip():
                        missing.append(f"{term}.{field}.{language}")
        self.assertEqual(missing, [], f"缺少翻譯：{missing}")

    def test_definitions_are_a_sentence_not_a_stub(self):
        # A one-word "definition" is a placeholder someone meant to come back
        # to. Chinese says more per character, hence the lower bound.
        short: list[str] = []
        for term, block in _entries().items():
            for language, minimum in (("en", 60), ("zh-Hant", 20), ("zh-Hans", 20)):
                text = _field(block, "definition", language)
                if len(text) < minimum:
                    short.append(f"{term}.{language} ({len(text)})")
        self.assertEqual(short, [], f"定義太短，像是還沒寫完：{short}")


class SimplifiedChineseTests(SimpleTestCase):
    """The zh-Hans text has to be translated, not converted."""

    def test_no_definition_is_copied_between_the_two_chinese_variants(self):
        copied = [
            term
            for term, block in _entries().items()
            if _field(block, "definition", "zh-Hant") == _field(block, "definition", "zh-Hans")
        ]
        self.assertEqual(
            copied,
            [],
            f"zh-Hans 的定義和 zh-Hant 完全一樣，代表沒有真的翻譯：{copied}",
        )

    def test_no_taiwan_only_vocabulary_in_the_simplified_text(self):
        problems: list[str] = []
        for term, block in _entries().items():
            for field in ("label", "definition"):
                text = _field(block, field, "zh-Hans")
                for taiwanese, mainland in TAIWAN_ONLY.items():
                    if taiwanese in text:
                        problems.append(f"{term}.{field}：{taiwanese} → 應為 {mainland}")
        self.assertEqual(problems, [], f"簡體版用了台灣用語：{problems}")

    def test_the_traditional_text_is_the_primary_one(self):
        # The user's own preference is Traditional, so an entry where the
        # Traditional definition is the shorter, thinner one usually means it
        # was written in Simplified first and back-converted.
        thin: list[str] = []
        for term, block in _entries().items():
            hant = len(_field(block, "definition", "zh-Hant"))
            hans = len(_field(block, "definition", "zh-Hans"))
            if hant and hans and hant < hans * 0.7:
                thin.append(f"{term} ({hant} vs {hans})")
        self.assertEqual(thin, [], f"繁體版明顯比簡體版單薄：{thin}")


class EnglishExpansionTests(SimpleTestCase):
    """An abbreviation without its expansion defeats the point of the request."""

    def test_every_abbreviation_carries_an_english_expansion(self):
        missing = [
            term
            for term, block in _entries().items()
            if re.search(r"^    abbr: '", block, re.M)
            and not re.search(r"^    expansion: '", block, re.M)
        ]
        self.assertEqual(missing, [], f"有縮寫但沒有英文全名：{missing}")

    def test_expansions_are_not_translated(self):
        # 'State of Charge' has to stay readable in a datasheet regardless of
        # the console's language.
        for term, block in _entries().items():
            match = re.search(r"^    expansion: '([^']*)'", block, re.M)
            if match is None:
                continue
            self.assertTrue(
                all(ord(char) < 0x2E80 for char in match.group(1)),
                f"{term} 的 expansion 應該保留英文原文：{match.group(1)!r}",
            )


class UsageTests(SimpleTestCase):
    """Every id used on a page exists, and every entry is either used or listed."""

    def _literal_ids(self) -> set[str]:
        """Ids written out as `<Term id="…">`. A typo here is a real bug."""
        found: set[str] = set()
        for path in FRONTEND.rglob("*.tsx"):
            if path.name == "Term.tsx":
                continue  # its own doc comment mentions example ids
            found.update(re.findall(r"<Term id=\"(\w+)\"", path.read_text(encoding="utf-8")))
        return found

    def _used_ids(self) -> set[str]:
        used = self._literal_ids()
        for path in FRONTEND.rglob("*.tsx"):
            text = path.read_text(encoding="utf-8")
            # A lookup table holds the glossary id alongside other strings, so
            # only the ones that match a real entry count as a use. Typos are
            # not this check's job - TypeScript rejects them at the table.
            used.update(_ids_from_lookup_tables(text) & set(_entries()))
        return used

    def test_no_page_references_a_term_that_does_not_exist(self):
        unknown = self._literal_ids() - set(_entries())
        self.assertEqual(unknown, set(), f"頁面引用了不存在的術語：{unknown}")

    def test_no_entry_is_silently_unused(self):
        orphans = set(_entries()) - self._used_ids() - REFERENCE_ONLY
        self.assertEqual(
            orphans,
            set(),
            "這些術語沒有出現在任何頁面上。要嘛在 UI 加上 <Term>，"
            f"要嘛加進 REFERENCE_ONLY 並說明原因：{sorted(orphans)}",
        )

    def test_the_reference_only_list_has_no_stale_names(self):
        stale = REFERENCE_ONLY - set(_entries())
        self.assertEqual(stale, set(), f"REFERENCE_ONLY 裡有已刪除的術語：{stale}")
