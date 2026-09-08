#!/usr/bin/env python3
"""The BLIND READ-BACK contract — the gate that reads the PICTURE instead of the file.

🔴 WHY THIS EXISTS. Every other check in this skill answers "what does the file contain". Seventy-odd
scripts read XML, geometry and pixel contrast; none of them reads the page as a page. The failure
that survives all of them is the one where the file is well-formed and the rendered slide does not
show what the record claims. From this repo's own record, every one of these shipped GREEN:

    a wireframe deck (one skeleton, zero components, three type sizes)   — caught by a human
    `<placeholder>` text that cleared every width floor                  — caught by adversarial review
    LibreOffice drawing negative bars as absolute values                 — caught by a human
    a deck of six grey blocks                                            — caught by "设计能力变弱了"
    an all-motif deck that shipped zero icons                            — caught by the user, first line
    Chinese text measured 46% short by every geometry gate               — caught by a human

`render_selfcheck` is the one mechanism aimed at this, and it is the ONLY gate artifact whose
CONTENT nothing verifies — its own docstring says so: "it proves the trace exists, not that the eye
judged well (a lazy `ok` on a bad slide still passes)". Measured: a 15-slide deck recorded `ok` on
all fifteen, and the user's first sentence named a defect on it.

WHAT THIS DOES DIFFERENTLY — three properties, each aimed at a way self-checking fails:

  1. BLIND. The reader is handed slide PNGs and a fixed question list, and is NOT handed the
     content record. It cannot restate a takeaway it never saw, so agreement means the picture
     carried the idea rather than the reader carrying it.
  2. COMPARATIVE. The gate computes DISAGREEMENTS between what was seen and what was recorded. It
     produces findings, not a score — there is nothing to write `ok` into.
  3. ANSWERED, NOT ASSERTED. Every finding needs a written resolution (fixed, or dismissed with a
     reason). A count cannot be acted on and a verdict cannot be forged into agreement.

🔴 THE HONEST LIMIT, stated the way `render_selfcheck` states its own. This proves that an
independent reader answered fixed questions about the pixels and that the disagreements were
computed mechanically rather than asserted. It does NOT prove the reader was truly blind if the
operator chose to leak the record into the packet, and it cannot see a defect the question list
never asks about. It is a floor under the critic, not a replacement for it.

USAGE

    python3 scripts/blind_read.py packet  <deck-dir>            # what the reader gets (record withheld)
    python3 scripts/blind_read.py compare <deck-dir> --answers answers.json [--write]
    python3 scripts/blind_read.py --selftest

Exit 0 clean · 1 findings/problems · 2 could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

GATES = ".deck-gates.json"

# ── the question list ────────────────────────────────────────────────────────────────────────────
# Fixed, because a reader who picks their own questions drifts toward the ones the page answers
# well. Each maps to a comparison below; a question nothing compares is a question not worth a
# round-trip.
QUESTIONS = (
    ("claim",
     "In ONE sentence: what is this page's single claim? If the page makes no claim, say so."),
    ("about",
     "In FIVE WORDS OR FEWER: what is this page about?"),
    ("largest",
     "What is the visually LARGEST / most dominant thing on the page? Name the thing, not its role."),
    ("elements",
     "Count what you can see, as an object with these integer keys: "
     "text_blocks, photos, icons, charts, diagrams, tables, marks. "
     "`icons` = small pictographic symbols standing for a category. `marks` = purely decorative "
     "shapes/rules/blocks carrying no content."),
    ("legible_text",
     "List VERBATIM every text string you can read at a glance. Do not paraphrase or tidy it."),
    ("unreadable",
     "List every element you could NOT identify within about one second. Empty list if none."),
    ("problems",
     "List anything visibly wrong: clipped or cut-off text, overlap, an image that does not match "
     "the words, colours that fight, something too small to read. Empty list if none."),
)
ELEMENT_KEYS = ("text_blocks", "photos", "icons", "charts", "diagrams", "tables", "marks")

# ── carves ───────────────────────────────────────────────────────────────────────────────────────
# A deck with genuinely nothing to look at. "Hard to arrange" is not on the list, and neither is
# "the runtime has no reader" — that case is `no-reader`, which is a DIFFERENT claim: it records
# that the deck went out without the check, instead of pretending the check passed.
CARVES = ("no-render", "no-reader", "tiny-ask", "user-waived")
MIN_TEXT = 12

# ── tokenisation ─────────────────────────────────────────────────────────────────────────────────
# 🔴 CJK-aware on purpose. A Latin-only tokenizer scores every Chinese deck at zero overlap and
# would fire on every slide of one — the exact CJK blindness this repo has already shipped once
# (every geometry gate measured Chinese text 46% short because it read <a:latin> for CJK runs).
_STOP = frozenset("""
a an the this that these those and or but if then so as at by for from in into of on to with
is are was were be been being it its his her their your our my we you they he she i
what which who whom how why when where can could may might will would shall should must
not no nor do does did done have has had page slide deck
""".split())
_CJK = r"一-鿿㐀-䶿぀-ヿ가-힯"


def tokens(text) -> list[str]:
    """Content tokens for overlap scoring, CJK-aware."""
    s = str(text or "").lower()
    out: list[str] = []
    for w in re.findall(r"[a-z0-9][a-z0-9'’\-]*", s):
        if len(w) > 1 and w not in _STOP:
            out.append(w)
    for run in re.findall("[" + _CJK + "]+", s):
        # Character BIGRAMS: single CJK characters are too promiscuous to mean agreement, and
        # bigrams approximate word boundaries without shipping a segmenter.
        out.extend([run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)])
    return out


def overlap(a, b) -> float:
    """Containment of the smaller token set in the larger, 0..1. Containment rather than Jaccard:
    a five-word `about` against a full-sentence takeaway is not a disagreement about content."""
    ta, tb = set(tokens(a)), set(tokens(b))
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


# 🔴 CALIBRATED ON REAL DATA, not chosen. Measured over 25 shipped slides read blind in two
# languages (a 15-page English deck and a 10-page Chinese one), scoring each reader claim against
# the takeaway its authors recorded:
#     deliberate divergence (the selftest's wrong-page fixtures) ....... 0.000
#     genuine agreement, wording differing freely ...................... 0.167 – 1.000
# So any floor in (0.00, 0.167) separates them. 0.10 sits between, with margin on both sides. The
# first draft used 0.20 — chosen, not measured — and it fired on a Chinese page whose claim and
# takeaway say the same thing in different words. What this floor knowingly gives up: a paraphrase
# that shares almost no vocabulary with its takeaway will not fire. That miss is the right trade —
# a check that cries wolf on correct pages gets answered with boilerplate, and then it is `ok` again.
CLAIM_FLOOR = 0.10
ABOUT_SAME = 0.80       # at or above this, two pages are about the same thing ON SCREEN

# Text that means the page is unfinished. The width floors cannot see these — a placeholder is as
# wide as real text, which is how `<...>` once cleared every one of them.
_PLACEHOLDER_RX = re.compile(
    r"(<[^>\n]{0,40}>)|(\{\{[^}\n]{0,40}\}\})|\b(lorem ipsum|tbd|todo|xxx+|placeholder|"
    r"click to add|your text here)\b|(占位|待定|待填|此处填)", re.I)

# ── classifying what the reader saw going wrong ──────────────────────────────────────────────────
# 🔴 WHY CLASSIFY AT ALL. Measured on the first real run: 15 slides produced 68 findings, 60 of them
# a straight relay of the reader's `problems`. Every one was real — but "write a resolution for each
# of 60" is enough friction to produce sixty `n/a`s, which is the `ok`-on-a-bad-slide failure this
# gate exists to end. So the relay is TRIAGED: things that are broken become findings that must be
# answered, and things that are matters of judgement become recorded OBSERVATIONS handed to the
# critic. Nothing is discarded; only the demand differs.
#
# Bilingual by construction. A reader looking at a Chinese deck answers in Chinese, and an
# English-only keyword set would silently classify every one of its findings as "taste" — the same
# CJK blindness this repo already shipped once in its geometry gates.
_CLIPPED = ("clipped", "cut off", "cut-off", "past the content", "past the edge", "off the edge",
            "beyond the frame", "outside the content area", "extends past", "runs off",
            "overflow", "overflows", "hangs below", "truncated", "被切", "截断", "出血", "溢出",
            "超出", "压边", "跑到边")
_OVERLAP = ("overlap", "overlaps", "overlapping", "collide", "collides", "colliding", "on top of",
            "sits over", "covers the", "重叠", "叠在", "压住", "遮住", "盖住")
_CONTRA = ("contradict", "contradicts", "contradiction", "does not match", "doesn't match",
           "inconsistent", "inconsistency", "disagrees with", "conflicts with", "矛盾", "不一致",
           "对不上", "不符")
_SAYS_BUT = re.compile(r"\bsays\b.{0,80}?\bbut\b|\bclaims\b.{0,80}?\bbut\b|写着.{0,40}?但", re.I | re.S)
_LEGIB = ("too small", "too faint", "low contrast", "low-contrast", "barely visible", "hard to read",
          "hard to parse", "illegible", "unreadable", "dim ", " dim", "faint", "太小", "太淡",
          "看不清", "对比度低", "难以辨认")
_UNKEYED = ("no key", "no legend", "without a key", "unlabelled", "unlabeled", "no explanation",
            "unexplained", "meaning unknown", "没有图例", "无图例", "没有标注", "未标注", "没有说明")
# Words that mean the clipped thing is TEXT. Clipped text is broken output; a shape bleeding off the
# edge is usually the register doing its job, so it is asked about rather than blocked.
_TEXTY = ("text", "line", "label", "caption", "word", "title", "headline", "footer", "paragraph",
          "descender", "sentence", "heading", "number", "字", "文字", "标题", "文案", "说明", "行")


def classify_problem(text) -> tuple[str, str] | None:
    """(code, severity) for a reported problem, or None if it is a matter of judgement.

    Judgement calls are not defects and must not be gated as if they were: "a page about food with
    no food imagery" is exactly the note a critic should make and exactly the note a build should
    be free to overrule."""
    t = str(text or "").lower()
    if any(k in t for k in _CONTRA) or _SAYS_BUT.search(t):
        return ("READ_CONTRADICTION", "hard")
    if any(k in t for k in _OVERLAP):
        return ("READ_OVERLAP", "hard")
    if any(k in t for k in _CLIPPED):
        return ("READ_CLIPPED", "hard" if any(w in t for w in _TEXTY) else "ask")
    if any(k in t for k in _LEGIB):
        return ("READ_LEGIBILITY", "ask")
    if any(k in t for k in _UNKEYED):
        return ("READ_UNKEYED", "ask")
    return None


# A takeaway that carries no content at all — a deck writes `—` on a cover that has no message.
# Comparing a claim against it scores 0.00 and reports the cover as a mismatch on every deck.
def has_content(text) -> bool:
    return bool(tokens(text))


# A page whose biggest thing is furniture. The wireframe deck and the six-grey-blocks deck both
# looked exactly like this from the reader's side.
_DECOR = ("background", "backdrop", "rectangle", "block", "blank", "empty", "shape", "panel",
          "decoration", "decorative", "gradient", "blob", "band", "bar of colour", "colour block",
          "color block", "grey box", "gray box", "背景", "色块", "方块", "装饰")

# Slide roles that legitimately carry almost nothing. Everything else must carry content.
_SPARSE_ROLES = ("cover", "title", "section", "divider", "closer", "close", "end", "thanks",
                 "q&a", "qa", "agenda")


# ── the reader packet ────────────────────────────────────────────────────────────────────────────
def render_pngs(deck_dir: Path, out_dir: str = "render") -> list[tuple[int, Path]]:
    """Slide PNGs, in order. Bookend thumbnails and contact sheets are not slides."""
    d = deck_dir / out_dir
    found = []
    if d.is_dir():
        for p in sorted(d.iterdir()):
            m = re.match(r"^slide(\d{2,})\.png$", p.name)
            if m:
                found.append((int(m.group(1)), p))
    return found


def stale(deck_dir: Path, pngs) -> list[str]:
    """PNGs older than the .pptx they claim to show. Reading a stale render is reading the previous
    deck, and it would report the previous deck's defects as fixed."""
    decks = sorted(deck_dir.glob("*.pptx"))
    if not decks or not pngs:
        return []
    newest = max(p.stat().st_mtime for p in decks)
    return [p.name for _, p in pngs if p.stat().st_mtime < newest]


def build_packet(deck_dir: Path, out_dir: str = "render") -> dict:
    """What the reader is handed. 🔴 Contains NO content record, NO takeaways, NO deck title —
    every one of those primes the answer this gate exists to obtain independently."""
    pngs = render_pngs(deck_dir, out_dir)
    if not pngs:
        raise SystemExit("[blind-read] no slide PNGs under {}/{} — render first, or claim the "
                         "`no-render` carve.".format(deck_dir, out_dir))
    old = stale(deck_dir, pngs)
    if old:
        raise SystemExit("[blind-read] {} PNG(s) are older than the .pptx ({}…). A stale render "
                         "shows the PREVIOUS deck; re-render before reading."
                         .format(len(old), ", ".join(old[:3])))
    # 🔴 A GAP IN THE NUMBERING SHRINKS THE DECK IN SILENCE. The slide count is derived from the
    # PNGs present, so a missing slide07.png makes a 15-slide deck look like a 14-slide one: the
    # coverage check then passes with that slide simply absent, and the page nobody rendered is the
    # page nobody reads. Refuse instead.
    nums = [n for n, _ in pngs]
    gaps = [i for i in range(1, max(nums) + 1) if i not in set(nums)]
    if gaps:
        raise SystemExit("[blind-read] the render is missing slide(s) {} (found {} PNGs numbered up "
                         "to {}). A gap silently shortens the deck — re-render the whole file."
                         .format(", ".join(map(str, gaps[:6])), len(pngs), max(nums)))
    return {"slides": [{"n": n, "png": str(p)} for n, p in pngs],
            "questions": [{"key": k, "ask": q} for k, q in QUESTIONS]}


# ── the comparison ───────────────────────────────────────────────────────────────────────────────
def _finding(n, code, severity, said):
    return {"n": n, "code": code, "severity": severity, "finding": said}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else 0


def _role_of(rec):
    return str((rec or {}).get("role") or "").strip().lower()


def _sparse_ok(rec, n, total):
    """May this page legitimately be nearly empty?"""
    r = _role_of(rec)
    if r:
        return any(k in r for k in _SPARSE_ROLES)
    return n == 1 or n == total          # no record: only the bookends get the benefit of the doubt


def compare(answers, content=None, design_plan=None, total=None) -> list[dict]:
    """Disagreements between what the reader SAW and what the record CLAIMS.

    `content` / `design_plan` may be None — a deck with no record still gets every record-free
    check (coverage, unreadable, placeholders, empty pages, on-screen repetition)."""
    out: list[dict] = []
    rows = [r for r in (answers or []) if isinstance(r, dict)]
    by_n = {}
    slides = {}
    if isinstance(content, dict):
        for s in content.get("slides") or []:
            if isinstance(s, dict) and isinstance(s.get("slide"), int):
                slides[s["slide"]] = s
    n_total = total or len(rows) or len(slides)

    # 1 — COVERAGE. Mirrors render_selfcheck: a slide with no answer is a slide nobody read.
    for i, r in enumerate(rows):
        n = r.get("n")
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= max(n_total, 1):
            out.append(_finding(0, "READ_COVERAGE", "hard",
                                "answers[{}].n is {!r} — must be a slide number in 1..{}."
                                .format(i, r.get("n"), n_total)))
            continue
        if n in by_n:
            out.append(_finding(n, "READ_COVERAGE", "hard",
                                "two answers both claim slide {} — one per slide.".format(n)))
            continue
        by_n[n] = r
    for n in range(1, (total or 0) + 1):
        if n not in by_n:
            out.append(_finding(n, "READ_COVERAGE", "hard",
                                "slide {} was never read — no answer for it.".format(n)))

    seen_about: dict[str, int] = {}
    icons_seen = photos_seen = 0

    for n in sorted(by_n):
        r = by_n[n]
        rec = slides.get(n)
        el = r.get("elements") if isinstance(r.get("elements"), dict) else {}
        counts = {k: _int(el.get(k)) for k in ELEMENT_KEYS}
        icons_seen += counts["icons"]
        photos_seen += counts["photos"]
        legible = [str(t) for t in (r.get("legible_text") or []) if str(t).strip()]
        unread = [str(t) for t in (r.get("unreadable") or []) if str(t).strip()]
        probs = [str(t) for t in (r.get("problems") or []) if str(t).strip()]
        largest = str(r.get("largest") or "").strip()
        claim = str(r.get("claim") or "").strip()
        about = str(r.get("about") or "").strip()

        # 2 — PLACEHOLDER ON SCREEN. Unambiguous, so it blocks.
        for t in legible:
            m = _PLACEHOLDER_RX.search(t)
            if m:
                out.append(_finding(n, "READ_PLACEHOLDER", "hard",
                                    "unfinished text is legible on the page: {!r}. The width floors "
                                    "cannot see this — a placeholder is as wide as real text."
                                    .format(t[:80])))
                break

        # 3 — THE PAGE CARRIES NOTHING. The wireframe / grey-blocks detector.
        carriers = sum(counts[k] for k in
                       ("photos", "icons", "charts", "diagrams", "tables")) + counts["text_blocks"]
        words = sum(len(tokens(t)) for t in legible)
        if not _sparse_ok(rec, n, n_total):
            if carriers <= 1 and words < 6:
                out.append(_finding(n, "READ_EMPTY", "hard",
                                    "the page carries nothing a viewer can take away: {} element(s), "
                                    "{} content word(s) legible. This is what a wireframe looks like "
                                    "from the audience's seat.".format(carriers, words)))
            elif counts["marks"] and carriers == 0:
                out.append(_finding(n, "READ_EMPTY", "hard",
                                    "the reader saw {} decorative mark(s) and no content element at "
                                    "all.".format(counts["marks"])))

        # 4 — THE BIGGEST THING IS FURNITURE.
        low = largest.lower()
        if largest and any(w in low for w in _DECOR) and not _sparse_ok(rec, n, n_total):
            out.append(_finding(n, "READ_HIERARCHY", "ask",
                                "the most dominant thing on the page is {!r} — furniture outranking "
                                "the content.".format(largest[:60])))
        if largest and any(overlap(largest, u) >= 0.8 for u in unread):
            out.append(_finding(n, "READ_HIERARCHY", "hard",
                                "the LARGEST thing on the page ({!r}) is also something the reader "
                                "could not identify.".format(largest[:60])))

        # 5 — DECODABILITY. Every on-frame element must read in about a second.
        for u in unread:
            out.append(_finding(n, "READ_UNREADABLE", "ask",
                                "not identifiable within ~1s: {}".format(u[:100])))

        # 6 — WHAT THE READER SAW GOING WRONG, TRIAGED. Broken → a finding to answer; judgement →
        # an observation for the critic. See classify_problem() for why the relay is not flat.
        for p in probs:
            hit = classify_problem(p)
            if hit:
                out.append(_finding(n, hit[0], hit[1], p[:200]))
            else:
                out.append(_finding(n, "READ_NOTE", "note", p[:200]))

        # 7 — THE PAGE READS AS SOMETHING ELSE. The core comparison.
        take = str((rec or {}).get("takeaway") or "").strip()
        if not has_content(take):
            take = ""                      # `—` on a cover is "no takeaway", not a takeaway of "—"
        if take and claim:
            sc = max(overlap(claim, take), overlap(about, take))
            if sc < CLAIM_FLOOR:
                out.append(_finding(n, "READ_CLAIM", "ask",
                                    "the page reads as {!r}; the record says its takeaway is {!r} "
                                    "(overlap {:.2f}). Either the page does not carry its message, "
                                    "or the record does not describe the page."
                                    .format(claim[:90], take[:90], sc)))
        elif take and not claim:
            out.append(_finding(n, "READ_CLAIM", "hard",
                                "the reader could state no claim for this page, but the record "
                                "gives it the takeaway {!r}.".format(take[:90])))

        # 8 — THE DECK REPEATS ITSELF ON SCREEN. The record forbids duplicate takeaways; this tests
        # whether that is true in the pixels, which is where the audience meets it.
        if about:
            for prev, pn in seen_about.items():
                if overlap(about, prev) >= ABOUT_SAME:
                    out.append(_finding(n, "READ_SAMENESS", "ask",
                                        "reads as the same page as slide {}: {!r} vs {!r}."
                                        .format(pn, about[:50], prev[:50])))
                    break
            seen_about[about] = n

    # 9 — PLANNED BUT NOT VISIBLE. The deck-wide checks: a plan that promises icons and a reader who
    # sees none is the measured Melbourne defect, and nothing in the pipeline could see it.
    dp = design_plan if isinstance(design_plan, dict) else {}
    fam = str(dp.get("icon_family") or "").strip().lower()
    if by_n and fam and fam not in ("none", "n/a", "-") and icons_seen == 0:
        out.append(_finding(0, "READ_PLAN_UNSEEN", "hard",
                            "the design plan sets `icon_family: {}`, and the reader saw ZERO icons "
                            "across all {} slides. Either they never reached the build, or they are "
                            "too small/faint to register.".format(fam, len(by_n))))
    return out


# ── the gate contract (imported by every gate path) ──────────────────────────────────────────────
def is_waived(rec) -> bool:
    return isinstance(rec, dict) and bool(str(rec.get("waived") or "").strip())


def waiver_faults(rec) -> list[str]:
    out: list[str] = []
    cat = str((rec or {}).get("waived_category") or "").strip().lower()
    if cat not in CARVES:
        out.append("needs a `waived_category` naming the carve: {}. A runtime with no reader is "
                   "`no-reader` — which RECORDS that the deck shipped unread, rather than implying "
                   "it was read.".format(" | ".join(CARVES)))
    if len(str((rec or {}).get("waived") or "").strip()) < MIN_TEXT:
        out.append("needs a written reason beside the category.")
    return out


def faults(rec, slide_count=None) -> list[str]:
    """Complaints about a SUPPLIED blind-read record. Empty means it is filled and answered."""
    out: list[str] = []
    if not isinstance(rec, dict):
        return [MISSING]
    answers = rec.get("answers")
    if not isinstance(answers, list) or not answers:
        out.append("`answers` is missing — one answer object per slide, from a reader that was not "
                   "shown the content record.")
        return out
    if slide_count and len(answers) != slide_count:
        out.append("`answers` has {} row(s) for a {}-slide deck — one per slide, covering every "
                   "slide.".format(len(answers), slide_count))
    missing_keys = set()
    for i, a in enumerate(answers):
        if not isinstance(a, dict):
            out.append("`answers[{}]` must be an object.".format(i))
            continue
        for k, _ in QUESTIONS:
            if k not in a:
                missing_keys.add(k)
    if missing_keys:
        out.append("every answer must carry all {} fields; missing: {}. The list is fixed because a "
                   "reader who picks their own questions drifts to the ones the page answers well."
                   .format(len(QUESTIONS), ", ".join(sorted(missing_keys))))
    fs = rec.get("findings")
    if not isinstance(fs, list):
        out.append("`findings` is missing — run `blind_read.py compare` and record what it "
                   "computed. An empty list is a legitimate result; an absent one means the "
                   "comparison never ran.")
        return out
    for i, f in enumerate(fs):
        if not isinstance(f, dict):
            out.append("`findings[{}]` must be an object.".format(i))
            continue
        sev = str(f.get("severity") or "").lower()
        if sev == "note":
            continue          # a judgement call the critic weighs; not a defect to answer
        res = str(f.get("resolution") or "").strip()
        if len(res) < MIN_TEXT:
            out.append("`findings[{}]` ({} on slide {}) has no resolution. Every finding is "
                       "ANSWERED in writing — what you changed, or why the reader was wrong. "
                       "`ok` is not an answer to a disagreement."
                       .format(i, f.get("code") or "?", f.get("n")))
        elif sev == "hard" and not str(f.get("fixed") or "").strip() \
                and len(str(f.get("refuted") or "").strip()) < MIN_TEXT:
            # 🔴 `refuted` exists because the reader is not infallible and must not be treated as
            # such. Measured on the first real run: the reader's `legible_text` for one slide
            # listed the same sentence under two different cards; the rendered page has no such
            # duplication — a transcription slip, not a deck defect. A gate whose only exit is
            # "fix it" turns that into a fake fix, which is worse than the finding.
            out.append("`findings[{}]` ({}) is a HARD finding — it needs `fixed` naming the change "
                       "that removed it, or `refuted` saying what you checked on the rendered page "
                       "that shows the reader was wrong.".format(i, f.get("code") or "?"))
    return out


MISSING = (
    'is missing. Step 5 now reads the PICTURE, not only the file: an independent reader that is NOT '
    'shown the content record answers a fixed question list about every slide PNG, and the '
    'disagreements against the record are computed rather than asserted.\n'
    '    python3 scripts/blind_read.py packet  <deck-dir>          # hand THIS to the reader\n'
    '    python3 scripts/blind_read.py compare <deck-dir> --answers answers.json --write\n'
    '  Then answer every finding in writing. Genuinely nothing to read? Claim a carve: '
    '{"blind_read": {"waived": "<why>", "waived_category": "' + " | ".join(CARVES) + '"}}')


# ── CLI ──────────────────────────────────────────────────────────────────────────────────────────
def _load_gates(deck_dir: Path) -> dict:
    p = deck_dir / GATES
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:                                    # noqa: BLE001 - report, never guess
        raise SystemExit("[blind-read] cannot read {}: {}".format(p, e))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", nargs="?", choices=("packet", "compare"))
    ap.add_argument("deck", nargs="?")
    ap.add_argument("--answers", help="JSON file (or - for stdin) of the reader's answers")
    ap.add_argument("--render-dir", default="render")
    ap.add_argument("--write", action="store_true",
                    help="write the answers + computed findings into .deck-gates.json")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)

    if a.selftest:
        return _selftest()
    if not a.cmd or not a.deck:
        ap.print_help()
        return 2
    deck = Path(a.deck).expanduser().resolve()
    if not deck.is_dir():
        print("[blind-read] not a directory: {}".format(deck), file=sys.stderr)
        return 2

    if a.cmd == "packet":
        pk = build_packet(deck, a.render_dir)
        print(json.dumps(pk, ensure_ascii=False, indent=2))
        print("\n# {} slide(s). Hand ONLY this to the reader — the content record stays behind."
              .format(len(pk["slides"])), file=sys.stderr)
        return 0

    if not a.answers:
        print("[blind-read] compare needs --answers <file|->", file=sys.stderr)
        return 2
    raw = sys.stdin.read() if a.answers == "-" else \
        Path(a.answers).expanduser().read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except Exception as e:                                    # noqa: BLE001
        print("[blind-read] answers are not valid JSON: {}".format(e), file=sys.stderr)
        return 2
    answers = parsed.get("answers") if isinstance(parsed, dict) else parsed
    if not isinstance(answers, list):
        print("[blind-read] expected a list of answers, or {\"answers\": [...]}.", file=sys.stderr)
        return 2

    gates = _load_gates(deck)
    total = len(render_pngs(deck, a.render_dir)) or None
    fs = compare(answers, gates.get("content"), gates.get("design_plan"), total)

    hard = [f for f in fs if f["severity"] == "hard"]
    notes = [f for f in fs if f["severity"] == "note"]
    ask = [f for f in fs if f["severity"] == "ask"]
    for f in fs:
        print("[{}] slide {} {}: {}".format(f["severity"].upper(), f["n"] or "-", f["code"],
                                            f["finding"]))
    print("\n[blind-read] {} finding(s): {} HARD (broken — fix and say what changed), {} ASK "
          "(answer in writing), {} note (judgement — for the critic, no answer owed)."
          .format(len(fs), len(hard), len(ask), len(notes)))

    if a.write:
        gates.setdefault("blind_read", {})
        gates["blind_read"]["answers"] = answers
        gates["blind_read"]["findings"] = [dict(f, resolution="", fixed="") for f in fs]
        (deck / GATES).write_text(json.dumps(gates, ensure_ascii=False, indent=2) + "\n",
                                  encoding="utf-8")
        print("[blind-read] wrote {} finding(s) into {}".format(len(fs), deck / GATES))
    return 1 if fs else 0


def _selftest() -> int:
    """Attack the comparator with the decks that actually shipped broken."""
    fails = []

    def want(codes, found, label):
        got = {f["code"] for f in found}
        if not set(codes) <= got:
            fails.append("{}: expected {}, got {}".format(label, sorted(codes), sorted(got)))

    def wantnt(codes, found, label):
        got = {f["code"] for f in found}
        if set(codes) & got:
            fails.append("{}: did NOT expect {}".format(label, sorted(set(codes) & got)))

    full = {k: ([] if k in ("legible_text", "unreadable", "problems") else "") for k, _ in QUESTIONS}
    full["elements"] = {k: 0 for k in ELEMENT_KEYS}

    def ans(n, **kw):
        r = dict(full)
        r["elements"] = dict(full["elements"])
        r["n"] = n
        r.update(kw)
        return r

    # the placeholder deck — cleared every width floor
    want(["READ_PLACEHOLDER"], compare([ans(1, claim="c", about="a", largest="title",
                                            legible_text=["<subtitle here>"],
                                            elements={**full["elements"], "text_blocks": 2})],
                                       total=1), "placeholder")
    # the wireframe / grey-blocks deck (slide 2 is a CONTENT page — the bookends are exempt below)
    want(["READ_EMPTY"], compare([ans(1, claim="x", about="x"), ans(2, claim="y", about="y"),
                                  ans(3, claim="z", about="z")], total=3), "wireframe")
    # bookends may be sparse
    wantnt(["READ_EMPTY"], compare([ans(1, claim="x", about="x")], total=1), "cover is sparse-ok")
    # furniture outranking content
    want(["READ_HIERARCHY"], compare(
        [ans(1), ans(2, claim="c", about="a", largest="a big grey background block",
                     legible_text=["real words here that carry the page"],
                     elements={**full["elements"], "text_blocks": 2}), ans(3)], total=3), "furniture")
    # the page reads as something else than the record claims
    rec = {"slides": [{"slide": 2, "takeaway": "book the ferry before you fly"}]}
    want(["READ_CLAIM"], compare(
        [ans(1), ans(2, claim="an 1837 survey divided the land into chains", about="the land survey",
                     largest="map", legible_text=["chains", "allotments", "survey of 1837"],
                     elements={**full["elements"], "text_blocks": 3, "photos": 1}), ans(3)],
        rec, total=3), "claim divergence")
    # …and agreement must NOT fire
    wantnt(["READ_CLAIM"], compare(
        [ans(1), ans(2, claim="book the ferry before you fly out", about="book the ferry early",
                     largest="ferry photo", legible_text=["book the ferry before you fly"],
                     elements={**full["elements"], "text_blocks": 2, "photos": 1}), ans(3)],
        rec, total=3), "claim agreement")
    # CJK must score like Latin, not at zero — the measured blindness
    rec_cn = {"slides": [{"slide": 2, "takeaway": "出发前先订好轮渡"}]}
    wantnt(["READ_CLAIM"], compare(
        [ans(1), ans(2, claim="出发前先订好轮渡票", about="先订轮渡", largest="轮渡照片",
                     legible_text=["出发前先订好轮渡"],
                     elements={**full["elements"], "text_blocks": 2, "photos": 1}), ans(3)],
        rec_cn, total=3), "CJK agreement")
    want(["READ_CLAIM"], compare(
        [ans(1), ans(2, claim="一八三七年的土地测量把城市划成方格", about="土地测量",
                     largest="地图", legible_text=["一八三七年的测量"],
                     elements={**full["elements"], "text_blocks": 3, "photos": 1}), ans(3)],
        rec_cn, total=3), "CJK divergence")
    # planned icons that never reached the page — the Melbourne defect
    want(["READ_PLAN_UNSEEN"], compare(
        [ans(1, claim="c", about="a", legible_text=["a real line of words on the page"],
             elements={**full["elements"], "text_blocks": 2, "photos": 1})],
        None, {"icon_family": "lucide"}, 1), "planned icons unseen")
    wantnt(["READ_PLAN_UNSEEN"], compare(
        [ans(1, claim="c", about="a", legible_text=["a real line of words on the page"],
             elements={**full["elements"], "text_blocks": 2, "icons": 3})],
        None, {"icon_family": "lucide"}, 1), "icons present")
    # a missing slide is visible, not silent
    want(["READ_COVERAGE"], compare([ans(1)], total=3), "coverage")
    # the deck repeating itself on screen
    want(["READ_SAMENESS"], compare(
        [ans(1), ans(2, claim="c", about="what melbourne costs",
                     legible_text=["a real line of words here"],
                     elements={**full["elements"], "text_blocks": 2, "photos": 1}),
         ans(3, claim="c2", about="what melbourne costs",
             legible_text=["another real line of words"],
             elements={**full["elements"], "text_blocks": 2, "photos": 1}), ans(4)],
        total=4), "sameness")

    # ── the triage. Verified against the problems a real reader actually wrote, EN and CN ────────
    def cls(txt, code, sev=None, label=""):
        got = classify_problem(txt)
        if code is None:
            if got is not None:
                fails.append("triage {}: judgement call classified as {}".format(label, got))
            return
        if not got or got[0] != code or (sev and got[1] != sev):
            fails.append("triage {}: expected {}/{}, got {}".format(label, code, sev, got))

    cls("The bottom footer line is cut off by the bottom edge of the slide — its descenders are "
        "clipped", "READ_CLIPPED", "hard", "clipped footer")
    cls("Day 1's body text overflows to a fourth line that hangs below the column's accent rule",
        "READ_CLIPPED", "hard", "overflow")
    # a shape bleeding off the edge is the register working, not broken output
    cls("The orange vertical stripe at the far left edge is cut off by the slide edge",
        "READ_CLIPPED", "ask", "decorative bleed")
    cls("The page number 15 overlaps the vertical band containing the CLOCKS body text",
        "READ_OVERLAP", "hard", "overlap")
    cls("Internal contradiction between body and source line: the paragraph says 24,000 residents "
        "across 50 cities while the source line says 150 cities",
        "READ_CONTRADICTION", "hard", "contradiction")
    cls("The headline says Two weeks a year but the timeline shows four separate events",
        "READ_CONTRADICTION", "hard", "says-but")
    cls("The list numbers are tiny orange digits, barely visible against the cream ground",
        "READ_LEGIBILITY", "ask", "legibility")
    cls("The three squares are unlabelled and have no legend", "READ_UNKEYED", "ask", "unkeyed")
    # judgement calls must NOT become defects — a build is free to overrule these
    cls("A page about food with no food imagery at all", None, label="taste: no imagery")
    cls("Large empty band across the lower third of the slide", None, label="taste: empty band")
    cls("Only one of the three items has a photo", None, label="taste: uneven photos")
    # 🔴 CJK must triage like Latin, or every Chinese deck reports all-taste and gates nothing
    cls("页脚那一行文字被切掉了", "READ_CLIPPED", "hard", "CN clipped text")
    cls("页码和正文重叠", "READ_OVERLAP", "hard", "CN overlap")
    cls("标题和正文的数字矛盾", "READ_CONTRADICTION", "hard", "CN contradiction")
    cls("序号太小，看不清", "READ_LEGIBILITY", "ask", "CN legibility")
    cls("三个方块没有图例", "READ_UNKEYED", "ask", "CN unkeyed")

    # a `—` takeaway means NO takeaway; comparing against it flags every cover on every deck
    if [f for f in compare(
            [ans(1, claim="a long title page about a trip", about="title page", largest="title",
                 legible_text=["Melbourne"], elements={**full["elements"], "text_blocks": 3})],
            {"slides": [{"slide": 1, "takeaway": "—"}]}, total=1) if f["code"] == "READ_CLAIM"]:
        fails.append("an empty `—` takeaway was compared as if it were a real one")

    # notes are recorded but owe no answer; asks and hards do
    noted = {"answers": [ans(1)], "findings": [{"n": 1, "code": "READ_NOTE", "severity": "note",
                                                "finding": "no imagery"}]}
    if faults(noted, 1):
        fails.append("a note demanded a resolution: {}".format(faults(noted, 1)))

    # the contract itself: a filled record with unanswered findings must NOT pass
    good = {"answers": [ans(1)], "findings": [{"n": 1, "code": "READ_CLAIM", "severity": "ask",
                                               "finding": "x", "resolution": ""}]}
    if not faults(good, 1):
        fails.append("faults(): an unanswered finding passed")
    good["findings"][0]["resolution"] = "the reader was right; reworded the header"
    if faults(good, 1):
        fails.append("faults(): an answered finding failed: {}".format(faults(good, 1)))
    hard_unfixed = {"answers": [ans(1)],
                    "findings": [{"n": 1, "code": "READ_EMPTY", "severity": "hard", "finding": "x",
                                  "resolution": "the reader was right about this one"}]}
    if not faults(hard_unfixed, 1):
        fails.append("faults(): a HARD finding with no `fixed` passed")
    # …but a reader CAN be wrong, and saying so with evidence must be a legal exit
    refuted = json.loads(json.dumps(hard_unfixed))
    refuted["findings"][0]["refuted"] = "re-read slide 12 at full size; no duplicated sentence"
    if faults(refuted, 1):
        fails.append("faults(): a refuted HARD finding failed: {}".format(faults(refuted, 1)))
    if not faults({"answers": [{"n": 1}], "findings": []}, 1):
        fails.append("faults(): an answer missing every question field passed")
    if waiver_faults({"waived": "no rendered deck exists at all", "waived_category": "no-render"}):
        fails.append("waiver_faults(): a properly claimed carve failed")
    if not waiver_faults({"waived": "too hard to arrange", "waived_category": "busy"}):
        fails.append("waiver_faults(): an invented carve passed")

    # determinism: no hash-salted anything (a fixture that passes by luck is the bug we shipped once)
    a1 = [f["code"] for f in compare([ans(1), ans(2)], total=2)]
    a2 = [f["code"] for f in compare([ans(1), ans(2)], total=2)]
    if a1 != a2:
        fails.append("compare() is not deterministic")

    for f in fails:
        print("FAIL " + f)
    print("[blind_read selftest] {}".format("FAILED: {}".format(len(fails)) if fails else "ok"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
