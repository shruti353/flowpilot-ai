"""Deterministic calendar-event title inference from free text.

The LLM is solely responsible for deciding whether a title is present, and
it sometimes leaves "title" out of a calendar.create_event action's
parameters even when the user's own wording makes a title obvious (e.g.
"a meeting with the AI team"). This module recognizes exactly two
unambiguous phrasings and derives a title from them; anything else returns
None rather than guessing, so genuinely under-specified requests still
surface as needs_clarification.
"""

import re

_WITH_TEAM_PATTERN = re.compile(
    # The article's trailing \s+ is inside the same optional group as the
    # article itself, so "a"/"an" can only match a whole word: against
    # "AI team" (no article), "a" would otherwise consume just the leading
    # "A" of "AI" and leave a mangled capture.
    r"meeting\s+with\s+(?:(?:the|my|our|a|an)\s+)?"
    r"([A-Za-z0-9&][A-Za-z0-9&\-]*(?:\s+[A-Za-z0-9&][A-Za-z0-9&\-]*)*?)"
    r"\s+team\b",
    re.IGNORECASE,
)

_ARTICLE_MEETING_PATTERN = re.compile(
    r"\b(?:a|an)\s+"
    r"([A-Za-z0-9&][A-Za-z0-9&\-]*(?:\s+[A-Za-z0-9&][A-Za-z0-9&\-]*)*?)"
    r"\s+meeting\b",
    re.IGNORECASE,
)


def _format_words(text: str) -> str:
    """Title-case each word, but preserve words that are already all-caps
    (e.g. "AI") instead of mangling them into "Ai"."""
    words = text.strip().split()
    return " ".join(word if word.isupper() else word.capitalize() for word in words)


def infer_meeting_title(user_text: str) -> str | None:
    """Infer a calendar event title from user text, or return None.

    Recognized patterns, in priority order:
    - "meeting with <X> team" -> "<X> Team Meeting"
    - "a/an <X> meeting"      -> "<X> Meeting"
    """
    if not user_text:
        return None

    match = _WITH_TEAM_PATTERN.search(user_text)
    if match:
        return f"{_format_words(match.group(1))} Team Meeting"

    match = _ARTICLE_MEETING_PATTERN.search(user_text)
    if match:
        return f"{_format_words(match.group(1))} Meeting"

    return None
