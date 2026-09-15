#!/usr/bin/env python3
"""Do the faces this deck NAMES actually resolve on the machine that measured it?

This is not the portability question. "Will the presenter have Calibri?" is unknowable from the
file and is correctly an advisory (PRE-FLIGHT 10). The question here is decidable and much more
consequential:

    every fit, wrap, overflow, footer-clearance and grid guard in this library sits on
    `deckkit._measure_lines`, which measures with the face it can RESOLVE. When the named face is
    absent, a metric-incompatible stand-in is measured instead, so the build and the lint are
    computed from the same wrong number and AGREE WITH EACH OTHER while the render disagrees with
    both.

`deckkit.font_health()` has always been able to see this, and `lint_layout` prints it — as a
`print`, not a finding. It is therefore in no `--json`, gates nothing, and is one line in a
scrolling build log. MEASURED, in this repo's own history: an install command that fit its panel
by 10% under substituted metrics still broke across three lines in the render and was copied back
as a repo path that 404s. MEASURED again on the LKEB/LUMC deck this check was written for: the
template's own theme font is Calibri, Calibri lives only inside the PowerPoint app bundle on
macOS, and the whole deck would have been laid out against a substitute — caught only because the
template's hand-written `profile.md` happened to warn about it.

Why it is not simply a CRITICAL in `lint_layout`: deckkit's shipped defaults are FONT='Calibri'
and MONO='Consolas', and NEITHER ships with macOS. Raising at build time would break every stock
build on the skill's primary platform on day one, and re-theming the defaults instead would be a
worse bug (it silently changes the look of every deck ever built from this library). So it lands
where the skill already puts blocking decisions that must not interrupt authoring: the HAND-OFF
gate, once, with a written waiver.

What it reports, per face the deck actually SETS on text:

  UNRESOLVED BODY FACE    a face carrying real text does not resolve here -> every geometry number
                          computed for that text is the wrong face's. Blocks.
  UNRESOLVED THEME FACE   the theme's major/minor latin face (which every run with no explicit
                          typeface inherits) does not resolve. Blocks.
  trace-only              a face carrying < `MIN_CHARS` characters is REPORTED, never blocked —
                          a stray run in a decorative face cannot move a layout.

    python3 scripts/check_fonts_resolve.py <deck.pptx> [--json] [--waive "<why>"]
    python3 scripts/check_fonts_resolve.py --selftest

Exit 0 clean · 1 findings · 2 could not run (NOT the same as clean, and it says so).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# A face carrying fewer characters than this cannot plausibly drive a wrap/fit decision that
# matters, so it is reported and never blocked. Deliberately low: a 12-character heading in the
# wrong face is exactly the kind of thing that overflows a title band.
MIN_CHARS = 8

# 🔴 deckkit's SHIPPED DEFAULTS are reported and never blocked, however much text they carry.
# The condition is identical either way — a substituted measurement — but the RESPONSIBILITY is
# not, and only one of the two is a decision anybody made:
#   * a face the author SET is a choice the machine cannot honour -> block, make them decide;
#   * a face the LIBRARY chose is an environment fact about this host. `FONT='Calibri'` and
#     `MONO='Consolas'` ship with neither macOS nor Linux, so blocking on them would refuse
#     delivery of a perfectly correct deck on essentially every stock machine — including this
#     repo's own Ubuntu CI, which is how the over-reach was caught: a suite that passes on a Mac
#     with Office fonts installed failed 8 assertions on CI, all of them "a thing that should
#     pass". A gate that fires on the whole population is not a floor, it is an outage.
# The fix for this arm is one call (`deckkit.use_platform_fonts()`), and it is named in the note.
# Read from deckkit's SOURCE, not from the live module: a build script assigns `dk.FONT = ...`
# before this runs, so the imported globals are the deck's choice, not the library's default —
# reading them would classify every author-set face as "shipped" and defeat the whole split.
# The literal set is the documented fallback and a test pins the two against each other.
_FALLBACK_DEFAULT_FACES = {"Calibri", "Consolas", "Arial", "STIX Two Math", "Cambria Math"}


def _shipped_defaults():
    import re as _re
    try:
        src = (pathlib.Path(__file__).with_name("deckkit.py")).read_text(encoding="utf8")
    except Exception:
        return set(_FALLBACK_DEFAULT_FACES)
    out = set()
    for attr in ("FONT", "MONO", "DISPLAY", "EAFONT", "EADISPLAY", "EQFONT", "EQ_MATHFONT"):
        m = _re.search(r"^%s\s*=\s*[\"']([^\"']+)[\"']" % attr, src, _re.M)
        if m:
            out.add(m.group(1))
    return out or set(_FALLBACK_DEFAULT_FACES)


DEFAULT_FACES = _shipped_defaults()

_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def _resolver():
    """`face -> bool` (does it resolve here), from deckkit, or None when deckkit is unavailable."""
    try:
        import deckkit
    except Exception:
        return None
    ff = getattr(deckkit, "_font_file", None)
    if not callable(ff):
        return None

    def ok(face):
        try:
            path = ff(face)
        except Exception:
            return None                              # cannot tell -> never claim either way
        if not path:
            return False
        # `_font_file` falls back to a stand-in rather than returning None, so a resolved PATH is
        # not by itself evidence the NAMED face was found. deckkit exposes the real predicate.
        try:
            return not deckkit._font_substituted(face)
        except Exception:
            return bool(path)
    return ok


def an_installed_face():
    """A family name this machine can actually resolve, or None.

    🔴 ASK the font machinery; never guess. A test that hardcodes "Helvetica on macOS, DejaVu Sans
    on Linux" is asserting a fact about somebody else's container, and it fails there for a reason
    that has nothing to do with the code under test — measured, on this repo's own Ubuntu CI,
    where `DejaVu Sans` does not resolve. The only honest source for "a face that resolves here"
    is the same resolver everything else in this module uses.
    """
    ok = _resolver()
    if ok is None:
        return None
    try:
        import matplotlib.font_manager as fm
        names = []
        seen = set()
        for f in fm.fontManager.ttflist:
            if f.name not in seen:
                seen.add(f.name)
                names.append(f.name)
    except Exception:
        names = []
    for face in names:
        if ok(face):
            return face
    return None


def _theme_faces(prs):
    """The theme's major/minor latin faces — what a run with no explicit typeface inherits."""
    out = set()
    try:
        for master in prs.slide_masters:
            for rel in master.part.rels.values():
                if not rel.reltype.endswith("/theme"):
                    continue
                from lxml import etree
                root = etree.fromstring(rel.target_part.blob)
                for slot in ("majorFont", "minorFont"):
                    el = root.find(".//" + _A + slot)
                    if el is None:
                        continue
                    latin = el.find(_A + "latin")
                    if latin is not None and latin.get("typeface"):
                        out.add(latin.get("typeface"))
    except Exception:
        pass
    return {f for f in out if f and not f.startswith("+")}


def _named_faces(prs):
    """{face: characters set in it} across every slide's runs.

    Reads the XML rather than python-pptx's `run.font.name` so that `ea` and `cs` typefaces — the
    CJK and complex-script faces, which carry the text on exactly the decks where substitution
    hurts most — are counted too.
    """
    counts = {}
    for slide in prs.slides:
        try:
            root = slide._element
        except Exception:
            continue
        for r in root.iter(_A + "r"):
            t = r.find(_A + "t")
            n = len(t.text or "") if t is not None else 0
            if not n:
                continue
            rPr = r.find(_A + "rPr")
            if rPr is None:
                continue
            for slot in ("latin", "ea", "cs"):
                el = rPr.find(_A + slot)
                face = el.get("typeface") if el is not None else None
                if not face or face.startswith("+"):
                    continue                          # "+mj-lt"/"+mn-lt" -> the theme face
                counts[face] = counts.get(face, 0) + n
    return counts


def check(pptx):
    """(findings, facts). findings = list of (severity, face, message). severity: 'block'|'note'."""
    try:
        from pptx import Presentation
        prs = Presentation(pptx)
    except Exception as exc:                          # unreadable deck -> exit 2, never "clean"
        raise RuntimeError("could not open %s: %s" % (pptx, exc))

    ok = _resolver()
    if ok is None:
        raise RuntimeError("deckkit is not importable, so font resolution cannot be tested here")

    named = _named_faces(prs)
    theme = _theme_faces(prs)
    findings, facts = [], {"named": named, "theme": sorted(theme), "unresolved": [],
                           "undecidable": []}

    for face, chars in sorted(named.items(), key=lambda kv: -kv[1]):
        good = ok(face)
        if good is None:
            facts["undecidable"].append(face)
            findings.append(("note", face,
                             "could not be tested on this machine — reported, not assumed fine"))
            continue
        if good:
            continue
        facts["unresolved"].append(face)
        shipped = face in DEFAULT_FACES
        sev = "note" if (shipped or chars < MIN_CHARS) else "block"
        if shipped:
            findings.append(("note", face,
                             "carries %d character(s) and does not resolve here, but it is one of "
                             "deckkit's SHIPPED DEFAULTS rather than a face this deck chose — an "
                             "environment fact about this host, not a defect in the deck. Every "
                             "wrap/fit number for it was still measured in a stand-in: fix with "
                             "deckkit.use_platform_fonts(), or install the face." % chars))
            continue
        findings.append((sev, face,
                         "carries %d character(s) of this deck's text but does NOT resolve here — "
                         "every wrap, fit and overflow number computed for it was measured in a "
                         "metric-incompatible stand-in%s"
                         % (chars, "" if sev == "block" else " (under the %d-character floor, so "
                            "reported only)" % MIN_CHARS)))

    for face in sorted(theme):
        if face in named:
            continue                                  # already judged above
        good = ok(face)
        if good is None:
            facts["undecidable"].append(face)
            continue
        if not good:
            facts["unresolved"].append(face)
            # 🔴 The shipped-default rule applies HERE TOO. It was written into the named-faces
            # loop above and not into this one, so a deck whose THEME names a default the host
            # lacks blocked unconditionally — and python-pptx's own default template declares
            # Calibri, which is absent from Linux. Net effect: every deck blocked on Ubuntu,
            # including this repo's CI fixtures. Three red runs, and it stayed invisible for two
            # of them because the failing assertion printed no evidence about WHICH face blocked.
            if face in DEFAULT_FACES:
                findings.append(("note", face,
                                 "is the THEME face inherited by runs with no explicit typeface "
                                 "and does not resolve here — but it is one of deckkit's SHIPPED "
                                 "DEFAULTS, an environment fact about this host rather than a "
                                 "choice this deck made. Fix with deckkit.use_platform_fonts(), "
                                 "or install the face."))
            else:
                findings.append(("block", face,
                                 "is the THEME face every run with no explicit typeface inherits, "
                                 "and it does not resolve here"))
    return findings, facts


def _selftest():
    bad = []
    ok = _resolver()
    if ok is None:
        print("[fonts] selftest SKIPPED — deckkit not importable")
        return 0
    # A face that certainly does not exist must read as unresolved; one deckkit itself falls back
    # to must read as resolved. Both directions, so a resolver that always says yes fails here.
    if ok("Definitely Not A Real Face 9Z") is not False:
        bad.append("a nonexistent face did not read as unresolved")
    known = an_installed_face()
    if known is None:
        print("  note: no resolvable face found on this host — the positive direction cannot be "
              "tested here, and that is reported rather than passed over")
    elif ok(known) is False:
        bad.append("%r was reported installed and then read as unresolved" % known)
    # MIN_CHARS must actually gate: a 1-character unresolved face is a note, not a block.
    if MIN_CHARS < 2:
        bad.append("MIN_CHARS floor is too low to distinguish a stray run from body text")
    for b in bad:
        print("  ✗", b)
    print("[fonts] selftest %s" % ("FAILED" if bad else "ok"))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", nargs="?")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--waive", default=None, help="a written reason; downgrades blocks to notes")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.pptx:
        ap.error("a deck path is required")
    try:
        findings, facts = check(a.pptx)
    except Exception as exc:
        print("[fonts] NOT CHECKED — %s" % exc)
        print("        NOT the same as clean: the faces this deck names were never tested.")
        return 2
    if a.json:
        print(json.dumps({"findings": [{"severity": s, "face": f, "why": m}
                                       for s, f, m in findings], "facts": facts}, indent=1))
    blocks = [f for f in findings if f[0] == "block"]
    if a.waive and blocks:
        print("[fonts] WAIVED — %s" % a.waive)
        for _s, f, m in findings:
            print("        %s: %s" % (f, m))
        return 0
    for s, f, m in findings:
        print("[fonts] %s %s: %s" % ("✗" if s == "block" else "•", f, m))
    if not findings:
        print("[fonts] every face this deck names resolves here (%d face(s) checked)"
              % (len(facts["named"]) + len(facts["theme"])))
    return 1 if blocks else 0


if __name__ == "__main__":
    raise SystemExit(main())
