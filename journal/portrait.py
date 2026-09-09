"""The portrait: a reading of the person, written across all fourteen answers.

Extraction (year.py) gives the facts -- who, where, which themes. Facts handed
back are an index, not value. What someone deserves after an hour of honest
answers is an interpretation: a name for where they stand, the arc of their
year, the tension underneath it, what they avoid and what it costs, how they
are with their people, what they are actually good at, the pattern to watch,
and where that leaves them.

Each section is one small, focused, schema-constrained call over the whole
transcript, because a 4B model writes a sharp paragraph far more reliably than
a long essay. This is a reading, not a mirror: a section reads their answers
back in its OWN words -- the relation between two answers, a pattern across
several, the gap between what they claim and what they show -- and a philosophical
lens where one genuinely fits. A draft that copies a stretch of their own words
verbatim is sent back to be paraphrased. Cached by transcript hash, so a
finished session is instant the second time.
"""
from __future__ import annotations

import hashlib
import json
import re as _re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from journal.review import Turn, turns
from journal.store import Page
from journal.year import ExtractorLike, cache_dir

SYSTEM = (
    "You are writing one section of a personal reading for someone who has just "
    "spent an hour answering fourteen honest questions about their year. You have "
    "all of their answers. Write directly to them, as 'you'.\n"
    "This is a reading, not a mirror. Do NOT quote their sentences back to them -- "
    "read them. Never copy more than three or four of their words in a row; say it "
    "back shorter and sharper than they did. A short phrase in quotation marks is "
    "allowed ONLY when one exact word they chose is itself the evidence -- rare, at "
    "most once in a section.\n"
    "Ground every observation in real evidence, and vary which kind you use:\n"
    "- a contrast: the most, the only, more than anything, not X but Y;\n"
    "- convergence: the same thing surfacing across two or three different answers;\n"
    "- the stated-vs-revealed gap: what they say about themselves against what the "
    "answers actually show;\n"
    "- one small, load-bearing detail that stands for the larger pattern.\n"
    "At least once, name what a thing actually is beneath their own label for it: "
    "'you call it X; it is closer to Y'.\n"
    "You may bring in ONE philosophical lens where it genuinely fits -- a named idea "
    "or thinker (the Stoic dichotomy of control, amor fati, bad faith, being vs. "
    "having, the examined life) -- but only as a tool turned on one specific thing "
    "they described, in the same breath, never a decorative epigraph. If none fits, "
    "use none; a forced reference is worse than none.\n"
    "The test for every sentence: would it be WRONG about a different person? If it "
    "could be said of almost anyone, cut it. No platitudes, no horoscope lines, no "
    "generic advice, no 'journey', no 'it's okay to', no lists of tips, and never "
    "summarise the questions. Be warm and unflinching -- say the true thing, kindly. "
    "Confident, plain sentences. Short paragraphs.\n"
    "Each section must bring something NEW: never make the same point another "
    "section made. Do not restate the person's final one-sentence answer unless "
    "this section is explicitly about it -- it is reserved for the ending.\n"
    "Get who-did-what right: the writer is the one speaking in every answer. If "
    "they wrote 'I told Maria the deadline wasn't real', then THEY told Maria -- "
    "never say Maria told them. Attribute words and actions only to the person "
    "the writer attributed them to.\n"
    "Vary your sentences: never begin more than two sentences the same way. "
    "Never mention answer numbers ('in answer 4') -- the reader sees a page, "
    "not a questionnaire.\n"
    "Output only JSON matching the schema."
)

# Which answers (1-based) each section should draw on, so the reading covers
# the whole person instead of circling the two most quotable lines.
FOCUS: dict[str, str] = {
    "name": "13 and 14, in the light of everything else",
    "year": "1, 4, 10 and 13",
    "tension": "4, 7, 8, 10 and 11 -- draw on at least two DIFFERENT answers",
    "avoiding": "7, 8 and 11 ONLY",
    "people": "2, 3, 9 and 11 ONLY -- do not bring in facts from other answers",
    "strengths": "4, 5, 7 and 12 ONLY",
    "pattern": "1, 4, 6, 8 and 10 -- it must show up in at least two of them",
    "standing": "13 and 14",
}
# Sections allowed to quote the reserved final answer.
MAY_QUOTE_CLOSING = {"name", "standing"}

_TEXT = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
_NAMED = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "text": {"type": "string"}},
    "required": ["name", "text"],
}
_KEEP = {
    "type": "object",
    "properties": {"text": {"type": "string"}, "keep": {"type": "string"}},
    "required": ["text", "keep"],
}
_STRENGTHS = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "minItems": 3,
            "maxItems": 3,
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "evidence": {"type": "string"}},
                "required": ["name", "evidence"],
            },
        }
    },
    "required": ["items"],
}

# (key, title shown on the page, instruction, schema)
SECTIONS: list[tuple[str, str, str, dict]] = [
    (
        "name",
        "A name for where you stand",
        "Give this person a name for where they stand right now, the way a "
        "personality type has a name: 'name' is two to five words, dignified, "
        "specific to them (e.g. 'The one who gives permission', 'The quiet "
        "shipper'). 'text' is ONE sentence saying why, in your own words -- the "
        "evidence for the name, not a quotation.",
        _NAMED,
    ),
    (
        "year",
        "Your year, read back to you",
        "Read their year back to them in 120 to 170 words: what it was mostly "
        "made of, the moment it hinged on (they named a turning point), and what "
        "that moment changed. Not a summary of answers -- an arc, told with "
        "confidence in your own words. End on the consequence of the turning "
        "point.",
        _TEXT,
    ),
    (
        "tension",
        "The tension underneath",
        "Find the ONE conflict that runs underneath several of their answers -- "
        "two things pulling against each other. 'name' is the tension as a short "
        "phrase in the form 'X vs. Y'. 'text' is 90 to 140 words showing where it "
        "surfaces across at least two different answers, in your own words. If a "
        "known dilemma fits it (control vs. acceptance, freedom vs. security, "
        "authenticity vs. belonging), name that axis to give it a shared shape.",
        _NAMED,
    ),
    (
        "avoiding",
        "What you are avoiding, and what it costs",
        "In 80 to 120 words: the thing they steer around (they named it, and it "
        "shows elsewhere too), what it protects them from, and what avoiding it "
        "has actually cost this year. Direct. Kind. In your own words, not "
        "quotation.",
        _TEXT,
    ),
    (
        "people",
        "Your people, read honestly",
        "Pick the two or three people who matter most in these answers. Write "
        "one short paragraph per person, each beginning with that person's name, "
        "on what that relationship actually is right now -- using ONLY what the "
        "writer wrote about that person. Do not invent events or feelings, and "
        "do not assign 'drifting', 'seeing' or 'silence' to someone unless the "
        "writer said so about them. 100 to 160 words in all. Do not quote; do not "
        "list facts. Read the relationship: what it costs, what it gives, what "
        "goes unsaid in it.",
        _TEXT,
    ),
    (
        "strengths",
        "What you are actually good at",
        "Three strengths this person clearly has, shown by what they wrote -- "
        "not flattery, evidence. A strength is something that served them or "
        "someone else; avoiding or fearing something is never a strength. Name "
        "each one as a short concrete phrase built "
        "from something THEY did or said -- a verb, a specific -- in two to six "
        "words. Never abstract virtue words (no 'resilience', 'authenticity', "
        "'self-care', 'perseverance', 'dedication', 'connection'). For a "
        "different person a name might be 'Calls her mother every Sunday'; "
        "invent names that fit THIS person's answers. Each 'evidence' is one "
        "sentence of behavioural evidence -- what they actually did, made, or "
        "carried, in your own words, not a quotation.",
        _STRENGTHS,
    ),
    (
        "pattern",
        "The pattern to watch",
        "One tendency that recurs across their answers AND costs them something "
        "-- e.g. saying 'fine' when it isn't, narrating instead of acting, waiting "
        "for someone else to notice. Not a strength, not praise, and not any of "
        "the strengths already named. 'name' is the pattern itself in three to "
        "seven plain words (never 'The pattern of ...', never the word 'pattern'). "
        "'text' is 70 to 110 words: where it shows up (across two different "
        "answers, in your own words) and what it quietly costs. A pattern, not a "
        "flaw; no advice.",
        _NAMED,
    ),
    (
        "standing",
        "Where you stand",
        "'text': 70 to 110 words on where they stand right now, honestly, and "
        "what their own answers point toward next -- not instructions, the "
        "direction already in their words. 'keep': ONE sentence for them to "
        "carry, in their own words if any sentence they wrote deserves it, "
        "otherwise one you write for them.",
        _KEEP,
    ),
]

# --- the four measures: a warm, generous score for each area of the year -----
#
# The app was built to refuse a report card. This is the deliberate exception:
# a headline read of four areas, scored 1-100 and always generous, so someone
# leaves the reading feeling seen and pointed somewhere -- what is working, and
# the one next step -- rather than only mirrored. It is a reading, not a verdict:
# there is no pass mark, no total, and every area is given its due even when the
# number is low.

# (label shown, what it covers, which answers it draws on)
AREAS: list[tuple[str, str, str]] = [
    ("Social", "your friends, family, and the people around you", "2, 3 and 9"),
    ("Love", "your closest relationship", "3 and 8"),
    ("Goals", "your work, your ambition, and what you made", "1, 4, 7 and 13"),
    ("Body & self", "your health, your money, and where you felt like yourself",
     "5, 6, 10 and 12"),
]
_DIRECTIONS = ("rising", "steady", "falling")

_AREAS_SCHEMA = {
    "type": "object",
    "properties": {
        "areas": {
            "type": "array",
            "minItems": len(AREAS),
            "maxItems": len(AREAS),
            "items": {
                "type": "object",
                "properties": {
                    "area": {"type": "string"},
                    "score": {"type": "integer", "minimum": 1, "maximum": 100},
                    "direction": {"type": "string", "enum": list(_DIRECTIONS)},
                    "working": {"type": "string"},
                    "next": {"type": "string"},
                },
                "required": ["area", "score", "direction", "working", "next"],
            },
        }
    },
    "required": ["areas"],
}

AREAS_SYSTEM = (
    "You are giving someone a warm, honest read on four areas of their year, "
    "after they answered fourteen questions about it. Write to them as 'you'.\n"
    "Score each area from 1 to 100. Be generous and encouraging -- this is meant "
    "to help them feel seen and hopeful, never to grade them harshly. Scale:\n"
    "  85-100  thriving -- a real source of life this year;\n"
    "  70-84   solid -- mostly good, with some strain;\n"
    "  55-69   mixed -- real tension and real effort both;\n"
    "  40-54   struggling -- this one needs tending;\n"
    "  25-39   painful or neglected -- name it gently.\n"
    "Most areas of a normal year land between 45 and 90. Reserve the bottom only "
    "for something they clearly described as painful; never score an area low just "
    "because they wrote little about it.\n"
    "'direction' is the momentum you read in their words: 'rising' if it is getting "
    "better, 'falling' if it is slipping, 'steady' otherwise.\n"
    "'working' and 'next' must each be built from a SPECIFIC they gave -- an actual "
    "person, project, place, or habit from their year. The test: if the sentence "
    "would fit a stranger who wrote none of these answers, it is wrong; rewrite it "
    "around their specific.\n"
    "'working' is ONE true sentence on what is genuinely good in this area -- always "
    "find something real, even when the score is low. Weak: 'You kept some of your "
    "relationships going.' Strong (a different person): 'You called your brother "
    "every Sunday, even the weeks you dreaded it.'\n"
    "'next' is ONE concrete action naming the actual person, project, or habit from "
    "their year -- not a category, not self-help, not a menu. NEVER write 'make time "
    "for', 'take time to', 'schedule time', 'focus on your', 'reconnect with', 'set "
    "an intention', 'be more', 'prioritise your', or 'whether that's X or Y'. Weak: "
    "'Schedule time to focus on your wellbeing.' Strong (a different person): 'Put "
    "the Tuesday run back on the calendar you dropped in March.'\n"
    "Do not quote their sentences back; read them in your own words. No platitudes.\n"
    "Each area is separate. Never reuse a point, a project, or a sentence across two "
    "areas. Work and what they made belong to Goals only; Body & self is their "
    "health, their money, and where they felt like themselves -- never put a work "
    "achievement there. 'next' is a real next step, not a repeat of what they "
    "already did.\n"
    "Score the four areas in the order given and label each exactly as named.\n"
    "Output only JSON matching the schema."
)

# The tells of generic self-help -- advice that fits a stranger. A 'working' or
# 'next' line that hits one of these is sent back to be built from a specific.
_GENERIC = _re.compile(
    r"\b("
    r"make (an? )?(deliberate )?(effort|time)|make time for|"
    r"take time to|carve out|set aside|spend (more )?time|"
    r"schedule (a |some )?time|set (a |an )?(clear )?intention|"
    r"focus on your|reflect on your|work on your|"
    r"reconnect with|open up to|prioriti[sz]e your|"
    r"be more |try to be |allow yourself to|give yourself|"
    r"whether (that|it)'?s"
    r")",
    _re.IGNORECASE,
)


@dataclass
class Section:
    key: str
    title: str
    text: str = ""
    name: str = ""
    keep: str = ""
    items: list[dict] = field(default_factory=list)


@dataclass
class Portrait:
    sections: list[Section] = field(default_factory=list)
    areas: list[dict] = field(default_factory=list)

    def get(self, key: str) -> Section | None:
        return next((s for s in self.sections if s.key == key), None)

    @property
    def complete(self) -> bool:
        return len(self.sections) >= len(SECTIONS) - 1


# --- the transcript the model reads --------------------------------------


def transcript(page: Page, script: list[str]) -> str:
    lines: list[str] = ["Their fourteen answers:", ""]
    for turn in turns(page, script):
        lines.append(f"{turn.index + 1}. {turn.question}")
        lines.append(turn.answer.strip() if turn.answer.strip() else "(skipped)")
        lines.append("")
    return "\n".join(lines).strip()


_QUOTE_RE = _re.compile(r"[\"“'‘]([^\"”'’]{6,})[\"”'’]")
_THIRD_PERSON = _re.compile(
    r"\b(the person|the writer|this person|one's own|oneself)\b", _re.IGNORECASE
)
_PLACEHOLDER_NAMES = {"name", "text", "keep", "title", "n/a", "none", ""}


def _drifts(section: Section) -> str:
    """Why a draft should be sent back, or '' if it is fine."""
    body = _section_text(section)
    if _THIRD_PERSON.search(body):
        return "it talked about them in the third person instead of to them as 'you'"
    if section.key in ("name", "tension", "pattern"):
        if section.name.lower().strip() in _PLACEHOLDER_NAMES or len(section.name.split()) < 2:
            return "the 'name' field was missing or a placeholder"
    if section.key == "pattern" and "pattern" in section.name.lower():
        return "the 'name' must be the tendency itself, not 'the pattern of ...'"
    return ""


def _redact(content: str, banned: list[str]) -> str:
    """Hide sentences earlier sections already quoted, keeping a stub so the
    thread of the answer survives. The strongest cure for an echo-chamber
    reading is not letting later sections see the same lines -- and never
    listing them in the prompt, where a small model would simply copy them."""
    if not banned:
        return content
    out = content
    for q in banned:
        words_q = q.split()
        if len(words_q) < 5:
            continue
        # Tolerate the punctuation and spacing between words, so a run captured as
        # bare words ("with attention one person at a time") still matches the
        # source that has commas ("with attention, one person at a time").
        pattern = _re.compile(
            r"\b" + r"[\W_]+".join(_re.escape(w) for w in words_q) + r"\b",
            _re.IGNORECASE,
        )

        def stub(match: "_re.Match[str]") -> str:
            words = _re.findall(r"[A-Za-z0-9']+", match.group(0))  # keep casing
            return " ".join(words[:4]) + " […]"

        out = pattern.sub(stub, out)
    return out


def _norm_quote(q: str) -> str:
    return " ".join(q.lower().split()).strip(" .,;:!?")


def _quotes_in(text: str, answers_lower: str) -> list[str]:
    """The writer's own words quoted in `text` (normalised), in order."""
    found: list[str] = []
    for quoted in _QUOTE_RE.findall(text):
        q = _norm_quote(quoted)
        if q and q in answers_lower and q not in found:
            found.append(q)
    return found


def _overlaps(a: str, b: str) -> bool:
    """Two quotes are 'the same' if one contains the other's core."""
    return a in b or b in a


_WORD = _re.compile(r"[a-z0-9']+")


def _copied_all(text: str, answers_lower: str, n: int = 6) -> list[str]:
    """Every maximal run of `n`+ consecutive words in `text` lifted verbatim from
    their answers. A reading paraphrases, so a long stretch copied straight from
    the answers -- quotation marks or not -- is a lift; a short signature phrase
    (< n words) is left alone."""
    haystack = " " + " ".join(_WORD.findall(answers_lower.lower())) + " "
    words = _WORD.findall(text.lower())
    runs: list[str] = []
    i, total = 0, len(words)
    while i <= total - n:
        if (" " + " ".join(words[i:i + n]) + " ") not in haystack:
            i += 1
            continue
        j = i + n
        while j < total and (" " + " ".join(words[i:j + 1]) + " ") in haystack:
            j += 1
        runs.append(" ".join(words[i:j]))
        i = j
    return runs


def _copied(text: str, answers_lower: str, n: int = 6) -> str:
    """The first verbatim lift in `text`, or '' if none -- the per-section gate."""
    runs = _copied_all(text, answers_lower, n)
    return runs[0] if runs else ""


def _prose(section: "Section") -> str:
    """The interpretive prose the copy-gate judges: text, name and any evidence
    items -- but NOT `keep`, which is by design one sentence in the writer's own
    words that they carry forward, and so is meant to be theirs."""
    return " ".join([section.text, section.name]
                    + [i["evidence"] for i in section.items])


_ANSWER_REF = _re.compile(
    r"\s*(?:\(|,\s*)?\b(?:in|from)\s+answers?\s+\d+(?:\s*(?:,|and|&)\s*\d+)*\)?",
    _re.IGNORECASE,
)


def _tidy(text: str) -> str:
    """Collapse whitespace and strip 'in answer 4'-style references -- the
    section is pointed at numbered answers, and a small model sometimes says
    so out loud."""
    cleaned = _ANSWER_REF.sub("", str(text))
    return " ".join(cleaned.split()).strip()


def _section_text(section: Section) -> str:
    return " ".join([section.text, section.name, section.keep]
                    + [i["evidence"] for i in section.items])


def write_section(engine: ExtractorLike, key: str, title: str, instruction: str,
                  schema: dict, content: str, answers_lower: str,
                  banned: list[str], closing: str, notes: str = "") -> Section:
    """One section, asked at most twice: once plainly, once more with the
    quotes it must not reuse spelled out."""
    section = Section(key=key, title=title)
    focus = FOCUS.get(key, "")
    reserved = "" if key in MAY_QUOTE_CLOSING else (
        "\nDo not quote or paraphrase their final one-sentence answer here."
    )
    content = _redact(content, banned)
    if notes:
        instruction = instruction + "\n" + notes
    problem = ""
    local_lifts: list[str] = []  # runs this section already lifted, hidden on retry
    for attempt in range(2):
        # On a retry, stub out the exact stretch the last draft copied, so the
        # model literally cannot lift it again and has to read it in its own words.
        view = _redact(content, local_lifts) if local_lifts else content
        avoid = ""
        if banned or local_lifts:
            avoid = (
                "\nSome lines are shown as […] because they have already been used; "
                "read other parts of their answers, in your own words."
            )
        nudge = "" if attempt == 0 else (
            f"\nYour previous draft was sent back because {problem}. Write it "
            "again: speak to them as 'you', fill every field with real content, "
            "read their answers back in your OWN words -- copy no phrase of theirs "
            "longer than a few words -- and make every sentence one that would be "
            f"wrong about someone else. Draw on answers {focus}."
        )
        prompt = (
            f"{SYSTEM}\n\nThis section: {instruction}\nDraw mainly on answers "
            f"{focus}.{reserved}{avoid}{nudge}"
        )
        raw = engine.extract_json(prompt, view, schema)
        try:
            obj = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(obj, dict):
            continue
        section.text = _tidy(obj.get("text", ""))
        section.name = _tidy(obj.get("name", ""))
        section.keep = _tidy(obj.get("keep", ""))
        if key == "name":
            # The name section is a name and ONE sentence; clamp a rambling draft.
            m = _re.search(r"^(.+?[.!?])(\s|$)", section.text)
            if m:
                section.text = m.group(1).strip()
        items = obj.get("items") or []
        section.items = [
            {"name": _tidy(i.get("name", "")), "evidence": _tidy(i.get("evidence", ""))}
            for i in items if isinstance(i, dict)
        ]
        prose = _prose(section)
        lifts = _copied_all(prose, answers_lower)
        copied = lifts[0] if lifts else ""
        quotes = _quotes_in(prose, answers_lower)
        reused = [q for q in quotes if any(_overlaps(q, b) for b in banned)]
        used_closing = bool(closing) and key not in MAY_QUOTE_CLOSING and any(
            _overlaps(q, closing) for q in quotes
        )
        drift = _drifts(section)
        if not copied and not reused and not used_closing and not drift:
            break
        local_lifts.extend(lifts)
        problem = (
            drift
            or ("it copied a whole stretch of their own words instead of reading "
                "them back in yours" if copied else "")
            or ("it leaned on a line another section already used" if reused else "")
            or ("it quoted the reserved final answer" if used_closing else "")
            or "it read as a horoscope line true of anyone"
        )
        if attempt == 1:
            break  # accept the second draft rather than block the reading
    return section


def write_areas(engine: ExtractorLike, content: str, answers_lower: str) -> list[dict]:
    """The four measures: one schema-constrained call scoring every area at once,
    so the numbers are calibrated against each other. Labels and score bounds are
    fixed here, never trusted from the model. A draft whose 'working'/'next' slide
    into generic self-help (advice that would fit a stranger) is sent back once,
    told which areas were generic; then whatever came back is coerced into shape
    rather than blocking the report."""
    listing = "\n".join(
        f"- {label}: {desc} (mainly answers {focus})" for label, desc, focus in AREAS
    )
    instruction = "Score these four areas, in this exact order:\n" + listing
    areas: list[dict] = []
    flagged: list[str] = []
    for attempt in range(2):
        nudge = "" if not flagged else (
            "\nThese areas need rewriting: " + ", ".join(flagged) + ". Their last "
            "draft was either generic self-help that would fit anyone, or borrowed "
            "another area's material. Rewrite each around the actual person, project, "
            "place, or habit from THEIR year, specific to that one area, as one "
            "concrete action -- and keep the areas distinct."
        )
        raw = engine.extract_json(f"{AREAS_SYSTEM}\n\n{instruction}{nudge}", content, _AREAS_SCHEMA)
        try:
            got = json.loads(raw).get("areas")
        except (ValueError, TypeError, AttributeError):
            got = None
        if not isinstance(got, list):
            got = []
        areas = []
        for i, (label, desc, _focus) in enumerate(AREAS):
            src = got[i] if i < len(got) and isinstance(got[i], dict) else {}
            try:
                score = max(1, min(100, int(src.get("score", 60))))
            except (ValueError, TypeError):
                score = 60
            direction = src.get("direction", "steady")
            if direction not in _DIRECTIONS:
                direction = "steady"
            areas.append({
                "area": label,  # the canonical label, never the model's
                "score": score,
                "direction": direction,
                "working": _tidy(src.get("working", "")),
                "next": _tidy(src.get("next", "")),
            })
        filled = all(a["working"] and a["next"] for a in areas)
        clean = not any(_copied(a["working"] + " " + a["next"], answers_lower) for a in areas)
        generic = {a["area"] for a in areas
                   if _GENERIC.search(a["next"]) or _GENERIC.search(a["working"])}
        flagged = sorted(generic | _duplicate_areas(areas))
        if filled and clean and not flagged:
            break
    return areas


def _duplicate_areas(areas: list[dict]) -> set[str]:
    """Areas whose 'working'/'next' share a long run with another area's -- the
    tell that the model reused one point (a work win landing under Body & self)
    instead of reading each area on its own."""
    dupes: set[str] = set()
    texts = [(a["area"], a["working"] + " " + a["next"]) for a in areas]
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            if _copied_all(texts[i][1], texts[j][1].lower(), n=6):
                dupes.update({texts[i][0], texts[j][0]})
    return dupes


def write_portrait(engine: ExtractorLike, page: Page, script: list[str],
                   on_progress: Callable[[int, int], None] | None = None) -> Portrait:
    content = transcript(page, script)
    answered = [t for t in turns(page, script) if t.answer.strip()]
    answers_lower = " ".join(t.answer.lower() for t in answered)
    closing = _norm_quote(answered[-1].answer) if answered and answered[-1].index == len(script) - 1 else ""
    portrait = Portrait()
    banned: list[str] = []
    total = len(SECTIONS) + 1  # the sections, then the four measures
    for i, (key, title, instruction, schema) in enumerate(SECTIONS):
        notes = ""
        if key == "pattern":
            strengths = portrait.get("strengths")
            if strengths and strengths.items:
                named = "; ".join(it["name"] for it in strengths.items if it["name"])
                notes = f"Strengths already named (the pattern must be something else): {named}."
        section = write_section(engine, key, title, instruction, schema, content,
                                answers_lower, banned, closing, notes)
        if section.text or section.name or section.items:
            portrait.sections.append(section)
            # Register both the quotation-marked quotes and any verbatim run this
            # section lifted, so a later section cannot lean on the same words --
            # cross-section repetition is most of what reads as "too much quoting".
            prose = _prose(section)
            marked = _quotes_in(prose, answers_lower)
            lifted = [_norm_quote(r) for r in _copied_all(prose, answers_lower)]
            for q in marked + lifted:
                # The closing sentence is reserved (handled by the reserved
                # rule), so it is never redacted -- the ending must still see it.
                if closing and _overlaps(q, closing):
                    continue
                if not any(_overlaps(q, b) for b in banned):
                    banned.append(q)
        if on_progress:
            on_progress(i + 1, total)
    portrait.areas = write_areas(engine, content, answers_lower)
    if on_progress:
        on_progress(total, total)
    return portrait


# --- cache -------------------------------------------------------------------


def _fingerprint(page: Page, script: list[str]) -> str:
    return hashlib.sha256(transcript(page, script).encode("utf-8")).hexdigest()[:24]


def _cache_path(directory: Path, page: Page, script: list[str]) -> Path:
    return cache_dir(directory) / f"portrait-{page.day.isoformat()}-{_fingerprint(page, script)}.json"


def load_cached_portrait(directory: Path, page: Page, script: list[str]) -> Portrait | None:
    path = _cache_path(directory, page, script)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        sections = []
        for s in data["sections"]:
            section = Section(**s)
            section.text, section.name, section.keep = _tidy(section.text), _tidy(section.name), _tidy(section.keep)
            sections.append(section)
        areas = data.get("areas", []) if isinstance(data.get("areas"), list) else []
        return Portrait(sections=sections, areas=areas)
    except (ValueError, TypeError, KeyError):
        return None


def save_cached_portrait(directory: Path, page: Page, script: list[str], portrait: Portrait) -> Path:
    cache_dir(directory).mkdir(parents=True, exist_ok=True)
    path = _cache_path(directory, page, script)
    path.write_text(json.dumps(asdict(portrait), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def portrait_for(directory: Path, engine: ExtractorLike | None, page: Page, script: list[str],
                 on_progress: Callable[[int, int], None] | None = None) -> Portrait | None:
    """Cached if the transcript is unchanged; otherwise written on the model."""
    cached = load_cached_portrait(directory, page, script)
    if cached is not None:
        return cached
    if engine is None:
        return None
    portrait = write_portrait(engine, page, script, on_progress)
    if portrait.sections:
        save_cached_portrait(directory, page, script, portrait)
    return portrait


# --- the deep reading: answer by answer, then a letter -----------------------
#
# The short report is the whole picture in one screen. The deep reading is the
# long form someone asks for by pressing "Go deeper": a short, honest read of
# each of their fourteen answers, one at a time, and then a letter that ties the
# year together. Written on demand and cached beside the portrait, keyed by the
# same transcript, so it is drawn once and instant thereafter.

DEEP_SYSTEM = (
    "You are writing part of a deep, honest personal reading for someone who has "
    "answered fourteen questions about their year. Write to them as 'you'.\n"
    "Do not quote their sentences back; read them in your own words -- never copy "
    "more than three or four of their words in a row. Say the true thing, kindly. "
    "Make every line specific enough to be WRONG about a different person: no "
    "platitudes, no horoscope lines, no advice lists, no 'journey'.\n"
    "Get who-did-what right: the writer is the one speaking in every answer. If "
    "they wrote 'I told Maria', then THEY told Maria -- never the reverse.\n"
    "Output only JSON matching the schema."
)

DEEP_ANSWER = (
    "Read ONE of their answers back to them, in 45 to 80 words, as 'you'. Not a "
    "summary of what they wrote -- what you SEE in it: the move they made, the "
    "thing underneath it, or the gap between what they say and what they show. Use "
    "the rest of their year only as quiet background. One clear paragraph."
)

LETTER = (
    "Write them a letter, to read after their reading -- 220 to 320 words, to them "
    "as 'you'. Tie their whole year together: what it was really about, the tension "
    "they carry, what you want them to see, and where their own answers already "
    "point next. Warm, plain, and human -- a letter, not a report; no headings, no "
    "lists. You may end on the one sentence they would keep. Output only JSON with "
    "a single 'text' field."
)


@dataclass
class Deep:
    answers: list[dict] = field(default_factory=list)  # {index, question, reading}
    letter: str = ""

    @property
    def complete(self) -> bool:
        return bool(self.letter) or bool(self.answers)


def write_deep_answer(engine: ExtractorLike, turn: "Turn", content: str,
                      answers_lower: str) -> str:
    """One honest paragraph on a single answer, asked at most twice."""
    pointer = (
        f"\n\nThe answer to read is number {turn.index + 1}:\n"
        f"{turn.question}\n{turn.answer.strip()}"
    )
    text = ""
    for attempt in range(2):
        nudge = "" if attempt == 0 else (
            "\nYour last draft copied their words or could be about anyone. Read it "
            "in your own words, specific to this one answer."
        )
        prompt = f"{DEEP_SYSTEM}\n\n{DEEP_ANSWER}{pointer}{nudge}"
        raw = engine.extract_json(prompt, content, _TEXT)
        try:
            text = _tidy(json.loads(raw).get("text", ""))
        except (ValueError, TypeError, AttributeError):
            text = ""
        if text and not _copied(text, answers_lower) and not _THIRD_PERSON.search(text):
            break
    return text


def write_letter(engine: ExtractorLike, content: str, answers_lower: str,
                 portrait: "Portrait | None") -> str:
    """The closing letter -- one call over the whole transcript, steered lightly
    by the names the reading already gave so it coheres with the rest."""
    guide = ""
    if portrait is not None:
        bits = []
        for key, kind in (("name", "you"), ("tension", "the tension"), ("pattern", "the pattern")):
            sec = portrait.get(key)
            if sec and sec.name:
                bits.append(f"{kind} '{sec.name}'")
        if bits:
            guide = ("\nFor coherence, the reading already named " + "; ".join(bits)
                     + " -- build on these, do not just restate them.")
    text = ""
    for attempt in range(2):
        nudge = "" if attempt == 0 else (
            "\nYour last draft was too short, copied their words, or drifted into "
            "the third person. Write the full letter to them as 'you', in your own "
            "words."
        )
        prompt = f"{DEEP_SYSTEM}\n\n{LETTER}{guide}{nudge}"
        raw = engine.extract_json(prompt, content, _TEXT)
        try:
            text = _tidy(json.loads(raw).get("text", ""))
        except (ValueError, TypeError, AttributeError):
            text = ""
        if (text and len(text.split()) >= 120
                and not _copied(text, answers_lower) and not _THIRD_PERSON.search(text)):
            break
    return text


def write_deep(engine: ExtractorLike, page: Page, script: list[str],
               portrait: "Portrait | None" = None,
               on_progress: Callable[[int, int], None] | None = None) -> Deep:
    content = transcript(page, script)
    answered = [t for t in turns(page, script) if t.answer.strip()]
    answers_lower = " ".join(t.answer.lower() for t in answered)
    deep = Deep()
    total = len(answered) + 1  # each answer, then the letter
    for i, turn in enumerate(answered):
        reading = write_deep_answer(engine, turn, content, answers_lower)
        if reading:
            deep.answers.append(
                {"index": turn.index, "question": turn.question, "reading": reading}
            )
        if on_progress:
            on_progress(i + 1, total)
    deep.letter = write_letter(engine, content, answers_lower, portrait)
    if on_progress:
        on_progress(total, total)
    return deep


def _deep_cache_path(directory: Path, page: Page, script: list[str]) -> Path:
    return cache_dir(directory) / f"deep-{page.day.isoformat()}-{_fingerprint(page, script)}.json"


def load_cached_deep(directory: Path, page: Page, script: list[str]) -> "Deep | None":
    path = _deep_cache_path(directory, page, script)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        answers = [a for a in data.get("answers", []) if isinstance(a, dict)]
        return Deep(answers=answers, letter=_tidy(data.get("letter", "")))
    except (ValueError, TypeError, KeyError):
        return None


def save_cached_deep(directory: Path, page: Page, script: list[str], deep: Deep) -> Path:
    cache_dir(directory).mkdir(parents=True, exist_ok=True)
    path = _deep_cache_path(directory, page, script)
    path.write_text(json.dumps(asdict(deep), ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def deep_for(directory: Path, engine: ExtractorLike | None, page: Page, script: list[str],
             portrait: "Portrait | None" = None,
             on_progress: Callable[[int, int], None] | None = None) -> "Deep | None":
    """Cached if already written for this transcript; otherwise written now."""
    cached = load_cached_deep(directory, page, script)
    if cached is not None:
        return cached
    if engine is None:
        return None
    deep = write_deep(engine, page, script, portrait, on_progress)
    if deep.answers or deep.letter:
        save_cached_deep(directory, page, script, deep)
    return deep
