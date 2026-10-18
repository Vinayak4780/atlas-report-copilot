"""Prompt-injection detection for retrieved documents and user questions.

Two layers of defence:
1. Detection + removal: paragraphs that look like instructions to an AI are cut out of the chunk
   before it reaches the LLM (the rest of the page, including real figures, is kept) and logged.
2. Isolation: every remaining excerpt is wrapped in <source> tags and the system prompt says that
   source content is data, never instructions (see agent/prompts.py).
"""
import re

INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your|system|any)\b"
        r"[^.\n]{0,20}\b(instructions?|prompts?|rules?|directions?|guidelines?)\b",
        r"\bnote to (ai|llm|language model|assistant|chatbot)s?\b",
        r"\b(ai|llm) (systems?|assistants?|models?)\s*:",
        r"\byou are now\b",
        r"\b(new|updated) (system )?instructions?\s*:",
        r"\bsystem prompt\b",
        r"\bjailbreak\b",
        r"\b(print|reveal|dump|output|list|show|display|exfiltrate)\b[^.\n]{0,50}\b(clients? table|contact e-?mails?|system prompt|api keys?|passwords?|credentials)\b",
        r"\bstate that this report is the only\b",
    )
]

REMOVED_MARKER = "[removed: text in this document that tried to instruct AI systems]"


def find_injection(text: str) -> str | None:
    """Returns the first matching fragment, or None."""
    for pattern in INJECTION_PATTERNS:
        m = pattern.search(text)
        if m:
            return m.group(0)
    return None


def sanitize_document_text(text: str) -> tuple[str, list[str]]:
    """Removes paragraphs containing injection attempts; keeps every other paragraph intact."""
    kept: list[str] = []
    hits: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        hit = find_injection(para)
        if hit:
            hits.append(para.strip()[:300])
            kept.append(REMOVED_MARKER)
        else:
            kept.append(para)
    return "\n\n".join(kept), hits
