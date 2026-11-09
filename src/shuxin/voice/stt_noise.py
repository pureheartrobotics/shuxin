"""Drop ASR hallucinations from fans, hiss, and other non-speech."""

from __future__ import annotations

import re

_MARKS = re.compile(r"[\s。．\.，,！!？?、]+")
_FILLER_ONLY = re.compile(r"^[啊阿嗯唔呃哦噢喔呀哈哼唉哎欸额恩姆呣]+$")
_LATIN_FILLER = re.compile(r"^(uh+|um+|hmm+|mm+|ah+|oh+|er+|mmhm+)$", re.IGNORECASE)


def is_noise_utterance(text: str) -> bool:
    """True when STT text is empty or a filler that noise often becomes."""
    compact = _MARKS.sub("", text or "")
    if not compact:
        return True
    if _FILLER_ONLY.fullmatch(compact):
        return True
    if _LATIN_FILLER.fullmatch(compact):
        return True
    return False
