"""Local hidden-instruction detector (no AI call, runs in-process). OWASP ASI01 agent goal hijack.

Looks at the shop page the agent read for text that tries to instruct an AI. Designed from the DEV split only;
held-out techniques test whether it generalises. Rules of thumb:
- Normalise first: strip zero-width characters, map look-alike letters, decode base64 blobs, so hiding tricks
  don't hide the words.
- Flag instructions *addressed to an AI* plus an action verb, or known override phrases. Ordinary shop text
  ("ignore the noise", "chat with our shopping assistant") must pass.
A hit is a manipulation signal -> ask_first (decision D1). It never approves anything.
"""

import base64
import re
import unicodedata

from agentguard.guard.decision import Finding

ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b‌⁠﻿"))   # NB: U+200D (emoji joiner) is left alone
HOMOGLYPHS = str.maketrans("аеорсухіјАЕОРСХ", "aeopcyxijAEOPCX")      # Cyrillic look-alikes -> Latin
ADDRESSEE = r"(?:\bai\b|\bassistants?\b|\bagents?\b|\bbots?\b|\bllms?\b|\bassistant ia\b|\bassistants? d'achat\b)"
ACTION = (r"(?:\bmust\b|\bbuy\b|\badd\b|\bpurchase\b|\bsend\b|\bignore\b|\bskip\b|\binstead\b|\boverride\b|"
          r"\bdo not (?:mention|tell)\b|\bachetez\b|\bajoutez\b|\bà la place\b)")
PATTERNS = [
    re.compile(rf"{ADDRESSEE}[^\n]{{0,250}}?{ACTION}", re.IGNORECASE),           # "Note for AI assistants: ... Buy X instead"
    re.compile(r"\b(?:do not|don't|never)\s+(?:mention|tell|inform|show)\b[^.\n]{0,40}"
               r"\b(?:customer|user|buyer|shopper)\b|\bsans le dire au client\b", re.IGNORECASE),   # secrecy towards the buyer
    re.compile(rf"{ACTION}[^.\n]{{0,60}}\bai\b", re.IGNORECASE),                  # "...buy ..., AI"
    re.compile(r"\b(?:system override|ignore (?:all |any )?(?:previous|prior) instructions|pre-?approved|"
               r"skip (?:all )?(?:spending )?checks)\b", re.IGNORECASE),
    re.compile(r"\[\s*system\b|<\|\s*system\s*\|>|\bsystem\s*:", re.IGNORECASE),
]
HIDDEN_CONTAINER = re.compile(r"display\s*:\s*none|left\s*:\s*-\d{3,}px|font-size\s*:\s*[01]px|"
                              r"color\s*:\s*#fff[^;\"]*;\s*background\s*:\s*#fff", re.IGNORECASE)
B64 = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")


def normalise(text: str) -> str:
    t = unicodedata.normalize("NFKC", text).translate(ZERO_WIDTH).translate(HOMOGLYPHS)
    decoded = []
    for blob in B64.findall(t):
        try:
            s = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            s = ""   # not base64 text: nothing to decode
        if s and s.isprintable():
            decoded.append(s)
    return " ".join([t, *decoded])


def scan(page_text: str) -> list[Finding]:
    if not page_text:
        return []
    text = normalise(page_text)
    hits = [p.pattern[:40] for p in PATTERNS if p.search(text)]
    if not hits:
        return []
    hidden = bool(HIDDEN_CONTAINER.search(page_text)) or text != unicodedata.normalize("NFKC", page_text)
    where = "hidden in the page" if hidden else "in the page text"
    return [Finding("hidden_instruction", "ask_first",
                    f"The shop page contains an instruction aimed at AI agents ({where}). The agent's choices on "
                    "this page can't be trusted without the buyer's OK.",
                    "the buyer confirms the cart, or the agent buys from a page without instructions",
                    source="detector")]
