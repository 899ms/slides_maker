#!/usr/bin/env python3
"""A registered template's `profile.md` must be OBEYED, not merely available.

🔴 WHY. The template registry is the one artefact in this skill that gets BETTER every time a
template is used: layout indices, the placeholders to drop, a bare decorative rectangle that must
be covered, which font the theme actually declares and whether it is installed. Measured by grep,
`profile.md` is read by `registry.py` and `deckkit.py` — both producers — and by NO check. A build
could ignore every line of it and nothing downstream would know.

Compare `check_direction_applied.py`, which exists precisely because "the look a user PICKED must
be verified against the deck that SHIPS". A template profile is the same claim with a longer
memory, and it had no such check. MEASURED, on the LKEB/LUMC template: the profile warns that the
title layout carries a bare grey rectangle which must be covered, and that the theme's Calibri
lives inside the PowerPoint app bundle on macOS so a Calibri deck is measured against a
substitute. Both are real traps, both were caught only because a human had written them down and
another human happened to read them.

HOW A PROFILE DECLARES A CONTRACT. `profile.md` stays prose — that is what makes it useful to a
reader — and gains ONE fenced block:

    ## Machine-checkable contract
    ```json
    {
      "match":       {"layout_names": ["1_Title and Content with Logo"],
                      "slide_size_in": [10.0, 5.625]},
      "layouts":     {"title": "Title Slide", "content": "1_Title and Content with Logo"},
      "fonts":       {"FONT": "Calibri"},
      "title_color": "FFFFFF",
      "must_cover":  [{"layout": "Title Slide", "rect": [7.14, 2.50, 2.54, 2.54],
                       "why": "a bare grey accent rectangle lives on the layout"}]
    }
    ```

One file, so the prose and the contract cannot drift into two truths. Every key is OPTIONAL: a
profile that declares only `match` + `fonts` is checked on fonts alone.

BINDING A DECK TO A PROFILE is by FINGERPRINT, not by trust: `match` is compared against the built
deck's own layout names and canvas size. That matters for the runtimes this skill does not
control — a Codex or Kimi run that never records which template it used still gets checked,
because the deck itself says.

🔴 NO CONTRACT, NO CLAIM. A registered template with no `## Machine-checkable contract` block
reports NOT CHECKED and exits 2. "There was nothing to check" and "everything checked out" are
different sentences and this never prints the second one for the first reason.

    python3 scripts/check_template_profile.py <deck.pptx> [--profile NAME] [--json]
    python3 scripts/check_template_profile.py --selftest

Exit 0 clean · 1 findings · 2 could not run / no contract.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EMU = 914400.0
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"

_P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"


def qn_p(tag):
    return _P + tag


def _sp_direct_fill(sp):
    """Does this shape DECLARE a fill on its own spPr? hex / "UNKNOWN" / None (paints nothing).

    Direct children only — never `.//`. A PowerPoint placeholder routinely carries `<a:noFill/>`
    in spPr plus an `<a14:hiddenFill>` with a real colour inside `spPr/a:extLst`; that hidden fill
    is what the shape WOULD be if it were filled, i.e. explicitly not painted.
    """
    try:
        spPr = sp.find(_P + "spPr")
        if spPr is None:
            return None
        for child in spPr:
            if child.tag == _A + "noFill":
                return None
            if child.tag in (_A + "blipFill", _A + "gradFill", _A + "pattFill"):
                return "UNKNOWN"
            if child.tag == _A + "solidFill":
                srgb = child.find(_A + "srgbClr")
                return srgb.get("val").upper() if srgb is not None else "UNKNOWN"
    except Exception:
        return None
    return None


CONTRACT_RE = re.compile(
    r"^##\s*Machine-checkable contract\s*$.*?^```(?:json)?\s*$(?P<body>.*?)^```\s*$",
    re.M | re.S)


# ─────────────────────────────────────────────────────────── loading profiles

def load_profiles():
    """[(name, dir, contract_dict_or_None, profile_path), ...] across every registry root."""
    out = []
    try:
        import registry
        pairs = registry.list_templates()
    except Exception:
        return out
    for name, d in pairs:
        pf = Path(d) / "profile.md"
        if not pf.exists():
            out.append((name, Path(d), None, pf))
            continue
        try:
            m = CONTRACT_RE.search(pf.read_text(encoding="utf8", errors="replace"))
        except OSError:
            out.append((name, Path(d), None, pf))
            continue
        if not m:
            out.append((name, Path(d), None, pf))
            continue
        try:
            out.append((name, Path(d), json.loads(m.group("body")), pf))
        except json.JSONDecodeError as exc:
            # a malformed contract is a LOUD problem, never a silent "no contract"
            out.append((name, Path(d), {"__error__": str(exc)}, pf))
    return out


def _deck_facts(prs):
    names, sizes = [], (prs.slide_width / EMU, prs.slide_height / EMU)
    for lay in prs.slide_layouts:
        try:
            names.append(lay.name)
        except Exception:
            pass
    return {"layout_names": names, "slide_size_in": [round(sizes[0], 3), round(sizes[1], 3)]}


def bind(prs, profiles, want=None):
    """The profile whose `match` fingerprint fits this deck — or None. `want` forces a name."""
    facts = _deck_facts(prs)
    if want:
        for name, d, c, pf in profiles:
            if name == want:
                return (name, d, c, pf)
        return None
    best = None
    for name, d, c, pf in profiles:
        if not isinstance(c, dict) or "__error__" in c:
            continue
        match = c.get("match") or {}
        want_names = [n for n in (match.get("layout_names") or []) if n]
        if want_names and not all(n in facts["layout_names"] for n in want_names):
            continue
        size = match.get("slide_size_in")
        if size and any(abs(float(a) - float(b)) > 0.05
                        for a, b in zip(size, facts["slide_size_in"])):
            continue
        if not want_names and not size:
            continue                                  # a match-less contract binds to nothing
        score = len(want_names) + (1 if size else 0)
        if best is None or score > best[0]:
            best = (score, (name, d, c, pf))
    return best[1] if best else None


# ─────────────────────────────────────────────────────────── the checks

def _run_colours(shape):
    out = []
    try:
        for p in shape.text_frame.paragraphs:
            for r in p.runs:
                if not (r.text or "").strip():
                    continue
                try:
                    rgb = r.font.color.rgb
                except Exception:
                    rgb = None
                out.append(str(rgb).upper() if rgb is not None else None)
    except Exception:
        pass
    return out


def _dominant_face(prs):
    counts = {}
    for slide in prs.slides:
        for r in slide._element.iter(_A + "r"):
            t = r.find(_A + "t")
            n = len(t.text or "") if t is not None else 0
            rPr = r.find(_A + "rPr")
            if not n or rPr is None:
                continue
            el = rPr.find(_A + "latin")
            face = el.get("typeface") if el is not None else None
            if face and not face.startswith("+"):
                counts[face] = counts.get(face, 0) + n
    return max(counts, key=counts.get) if counts else None


def check(pptx, want=None):
    """(findings, facts). findings = [(code, message), ...]. Raises when it cannot run."""
    from pptx import Presentation
    prs = Presentation(pptx)
    profiles = load_profiles()
    if not profiles:
        raise RuntimeError("no template profiles are registered (scripts/registry.py --list)")
    bound = bind(prs, profiles, want=want)
    if bound is None:
        # A profile with no contract block has no `match` fingerprint either — the fingerprint
        # lives IN the contract — so it is genuinely unbindable rather than merely unchecked.
        # Saying which registered templates are in that state is the actionable half: "no template
        # matched" and "the template that would have matched declares nothing checkable" lead to
        # different next moves, and only one of them is the reader's to fix.
        mute = [n for n, _d, c, _pf in profiles if c is None]
        hint = ("" if not mute else
                " — note that %s registered template(s) declare no `## Machine-checkable contract` "
                "block and therefore cannot be matched at all: %s"
                % (len(mute), ", ".join(sorted(mute))))
        raise RuntimeError(
            "this deck matches no registered template profile's `match` fingerprint" + hint)
    name, _d, contract, pf = bound
    if contract is None:
        raise RuntimeError(
            "template %r has a profile.md but NO `## Machine-checkable contract` block, so nothing "
            "about it can be verified against the built deck (%s)" % (name, pf))
    if "__error__" in contract:
        raise RuntimeError("template %r has a malformed contract block: %s"
                           % (name, contract["__error__"]))

    finds, facts = [], {"template": name, "profile": str(pf), "checked": []}

    # 1 ─ the layouts the profile names must be the layouts the deck actually uses
    want_layouts = contract.get("layouts") or {}
    if want_layouts:
        facts["checked"].append("layouts")
        allowed = {v for v in want_layouts.values() if isinstance(v, str)}
        used = {}
        for i, slide in enumerate(prs.slides, 1):
            try:
                used.setdefault(slide.slide_layout.name, []).append(i)
            except Exception:
                pass
        facts["layouts_used"] = used
        if allowed:
            stray = {k: v for k, v in used.items() if k not in allowed}
            if stray:
                finds.append(("LAYOUT OFF PROFILE",
                              "slides %s use layout(s) the profile does not name (%s). The profile "
                              "records which layouts carry this template's branding; anything else "
                              "is an untested surface."
                              % (", ".join(str(n) for v in stray.values() for n in sorted(v)),
                                 ", ".join(sorted(stray)))))

    # 2 ─ the font the profile decided on
    want_fonts = contract.get("fonts") or {}
    if want_fonts.get("FONT"):
        facts["checked"].append("fonts")
        dom = _dominant_face(prs)
        facts["dominant_face"] = dom
        if dom and dom != want_fonts["FONT"]:
            finds.append(("FONT OFF PROFILE",
                          "the profile decided FONT=%r for this template and the deck is set in "
                          "%r. A template's type decision is the part a later deck is most likely "
                          "to re-litigate by accident." % (want_fonts["FONT"], dom)))

    # 3 ─ the title colour the profile requires on the branded band
    want_title = (contract.get("title_color") or "").upper().lstrip("#")
    if want_title:
        facts["checked"].append("title_color")
        bad = []
        for i, slide in enumerate(prs.slides, 1):
            try:
                title = slide.shapes.title
            except Exception:
                title = None
            if title is None or not (title.text_frame.text or "").strip():
                continue
            cols = [c for c in _run_colours(title) if c]
            if cols and all(c != want_title for c in cols):
                bad.append((i, cols[0]))
        facts["title_colors"] = bad
        if bad:
            finds.append(("TITLE COLOUR OFF PROFILE",
                          "the profile requires #%s on this template's title band; slide(s) %s set "
                          "the title in another colour (%s). On a coloured band this is the "
                          "difference between a readable title and an invisible one."
                          % (want_title, ", ".join(str(n) for n, _ in bad),
                             ", ".join(sorted({c for _, c in bad})))))

    # 4 ─ decorative furniture the profile says the BUILD must cover
    covers = contract.get("must_cover") or []
    if covers:
        facts["checked"].append("must_cover")
        uncovered = []
        for spec in covers:
            rect = spec.get("rect") or []
            if len(rect) != 4:
                continue
            rx, ry, rw, rh = (float(v) for v in rect)
            lay_name = spec.get("layout")
            area = max(rw * rh, 1e-6)
            for i, slide in enumerate(prs.slides, 1):
                try:
                    if lay_name and slide.slide_layout.name != lay_name:
                        continue
                except Exception:
                    continue
                best = 0.0
                for sh in slide.shapes:
                    # 🔴 Only a shape that actually PAINTS can cover anything. An empty text box
                    # overlapping the rect satisfies a naive containment test and covers nothing —
                    # caught in this checker's own test, which "covered" the LKEB grey block with a
                    # transparent textbox and passed. A picture counts; an <p:sp> counts only when
                    # it declares a real fill.
                    try:
                        el = sh._element
                        if el.tag == qn_p("pic"):
                            pass
                        elif el.tag == qn_p("sp"):
                            if _sp_direct_fill(el) is None:
                                continue
                        else:
                            continue          # graphicFrame/group: cannot confirm it paints
                        l, t = sh.left / EMU, sh.top / EMU
                        w, h = sh.width / EMU, sh.height / EMU
                    except (TypeError, AttributeError):
                        continue
                    ix = max(0.0, min(l + w, rx + rw) - max(l, rx))
                    iy = max(0.0, min(t + h, ry + rh) - max(t, ry))
                    best = max(best, ix * iy / area)
                if best < 0.9:
                    uncovered.append((i, spec.get("why") or "declared furniture", round(best, 2)))
        facts["uncovered"] = uncovered
        if uncovered:
            finds.append(("UNCOVERED TEMPLATE FURNITURE",
                          "; ".join("slide %d leaves %s exposed (%.0f%% covered)"
                                    % (n, why, frac * 100) for n, why, frac in uncovered)
                          + ". The profile records it because it cannot be deleted from a layout "
                            "— it has to be covered by the build."))
    if not facts["checked"]:
        raise RuntimeError("template %r declares a contract block with no checkable keys" % name)
    return finds, facts


def _selftest():
    bad = []
    body = '{"match": {"layout_names": ["X"]}, "fonts": {"FONT": "Calibri"}}'
    doc = "# t\n\nprose\n\n## Machine-checkable contract\n```json\n%s\n```\n\nmore prose\n" % body
    m = CONTRACT_RE.search(doc)
    if not m:
        bad.append("the contract block was not found in a normal profile.md")
    elif json.loads(m.group("body")).get("fonts", {}).get("FONT") != "Calibri":
        bad.append("the contract block parsed to the wrong value")
    if CONTRACT_RE.search("# t\n\nprose only, no contract\n"):
        bad.append("a profile with NO contract block was read as having one")
    # a contract with no `match` must bind to nothing rather than to everything
    class _P:
        slide_width = int(10 * EMU); slide_height = int(5.625 * EMU)
        slide_layouts = []
    if bind(_P(), [("x", Path("."), {"fonts": {"FONT": "A"}}, Path("p"))]) is not None:
        bad.append("a contract with no `match` fingerprint bound to a deck anyway")
    for b in bad:
        print("  ✗", b)
    print("[template-profile] selftest %s" % ("FAILED" if bad else "ok"))
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pptx", nargs="?")
    ap.add_argument("--profile", default=None, help="force a template name instead of fingerprinting")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return _selftest()
    if not a.pptx:
        ap.error("a deck path is required")
    try:
        finds, facts = check(a.pptx, want=a.profile)
    except Exception as exc:
        print("[template-profile] NOT CHECKED — %s" % exc)
        print("        NOT the same as clean.")
        return 2
    if a.json:
        print(json.dumps({"findings": [{"code": c, "why": m} for c, m in finds],
                          "facts": facts}, indent=1))
    for c, m in finds:
        print("[template-profile] ✗ %s: %s" % (c, m))
    if not finds:
        print("[template-profile] %r honoured — checked: %s"
              % (facts["template"], ", ".join(facts["checked"])))
    return 1 if finds else 0


if __name__ == "__main__":
    raise SystemExit(main())
