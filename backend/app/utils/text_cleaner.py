"""
Text cleaning utilities — remove PDF artefacts common in academic papers.
"""
import re


class TextCleaner:
    # Patterns to strip
    _PAGE_NUMBER_RE = re.compile(r"^\s*\d+\s*$", re.MULTILINE)
    _HEADER_FOOTER_RE = re.compile(
        r"^\s*(arXiv|proceedings|conference|workshop|journal|preprint|copyright.*?\d{4})",
        re.IGNORECASE | re.MULTILINE,
    )
    _HYPHEN_BREAK_RE = re.compile(r"(\w+)-\n(\w+)")
    _EXTRA_WHITESPACE_RE = re.compile(r" {2,}")
    _LINE_BREAK_IN_PARA_RE = re.compile(r"(?<!\n)\n(?!\n)")

    def clean(self, text: str) -> str:
        """Apply all cleaning steps and return a cleaned string."""
        text = self._PAGE_NUMBER_RE.sub("", text)
        text = self._HEADER_FOOTER_RE.sub("", text)
        text = self._HYPHEN_BREAK_RE.sub(r"\1\2", text)     # re-join hyphenated words
        text = self._LINE_BREAK_IN_PARA_RE.sub(" ", text)   # join soft line breaks
        text = self._EXTRA_WHITESPACE_RE.sub(" ", text)
        return text.strip()

    def remove_references_section(self, paragraphs: list[str]) -> list[str]:
        """Drop all paragraphs that appear after a 'References' heading."""
        ref_keywords = {"references", "bibliography", "works cited"}
        out: list[str] = []
        for para in paragraphs:
            if para.strip().lower() in ref_keywords:
                break
            out.append(para)
        return out


text_cleaner = TextCleaner()
