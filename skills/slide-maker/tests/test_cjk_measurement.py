#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""On a 中文 deck the ruler was short by 46%, and every geometry check used it.

`_natural_width_in` was never wrong — hand it a face that covers CJK and it is exact. What was
wrong was the FACE handed to it. `_ink_rect` resolved a run's face with `run.font.name`, and
python-pptx's `font.name` reads `<a:latin>`; CJK glyphs render from `<a:ea>`, where `set_font` /
`_apply_ea` put the East-Asian face. Measured on one real subtitle at 13pt (27 full-width glyphs,
true width 4.8750in):

    Hiragino Sans GB   4.8750in   exact
    Songti SC          4.8750in   exact
    Helvetica Neue     2.6181in   54% — what every check was actually using

That under-measurement reaches TEXT_OVERLAP, OFF_CANVAS, ESCAPES_CARD, FOOTER and every geometry
decision built on ink rectangles, i.e. essentially all of this file's geometry on a Chinese deck.
Its signature in practice is the worst kind: a page collides after a generous-looking margin was
left, and nudging coordinates gives feedback that does not match intuition — so the operator
blames their own arithmetic rather than the ruler.

The resolution goes through `_inherited_ea`, not through a second width model and not through a
`_is_wide` branch: a supplied CJK template normally sets the face one level up (paragraph
`defRPr`, the shape's `lstStyle`), and that is the same chain `retrofit_ea` and `CJK_NO_EA`
already walk — so all three agree by construction rather than by coincidence.

Run:  python3 tests/test_cjk_measurement.py
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import deckkit as dk                                                  # noqa: E402
from deckkit import Inches, Pt                                        # noqa: E402
from pptx.oxml.ns import qn                                           # noqa: E402

PASS, FAIL, SKIP = [], [], []
CJK = "给准备申请的人——学位、博士、岗位，三扇门分别长什么样"   # 27 glyphs
TRUE_W = 27 * 13 / 72.0                                              # full-width at 13pt
LATIN = "A subtitle running straight across the page"
EA, LAT = "Hiragino Sans GB", "Helvetica Neue"

# 🔴 An absolute width is only meaningful where the face is actually INSTALLED. On a bare CI
# runner none of these exist and every one of them substitutes to DejaVu Sans, which carries no
# CJK glyphs — so 27 full-width characters measure 3.0697in there instead of 4.8750in no matter
# which face name the code resolves. The first version of this suite asserted the macOS numbers
# unconditionally and went red on GitHub while passing locally: it was testing the runner's font
# directory, not the fix. What the fix actually does is resolve the FACE, so that is what is
# asserted everywhere; the inch values are asserted only where they can be true.
HAVE_CJK_FONT = not dk._font_substituted(EA)


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  — " + str(detail)) if detail and not cond else ""))


def check_metric(name, cond, detail=""):
    """A check whose truth depends on a real CJK font being installed."""
    if not HAVE_CJK_FONT:
        SKIP.append(name)
        print("  skip " + name + "  — %r is not installed here; width would be DejaVu's" % EA)
        return
    check(name, cond, detail)


def face_of(text, latin="Helvetica Neue", ea=None, inherited=None, size=13):
    """The face `_ink_rect` will MEASURE this run in — the fix, isolated from font metrics."""
    sh = _shape(text, latin, ea, inherited, size)
    r = sh.text_frame.paragraphs[0].runs[0]
    return dk._measuring_face(r)


def _shape(text, latin, ea, inherited, size):
    """One un-wrapped run in a textbox, with the ea face supplied in whichever of the three
    places a real deck puts it: the deck default, the run itself, or one level up."""
    dk.FONT, dk.EAFONT = LAT, EA
    prs = dk.blank_deck()
    s = dk.add_slide(prs)
    if inherited:
        tb = s.shapes.add_textbox(Inches(0.62), Inches(2.0), Inches(8.76), Inches(0.4))
        tb.text_frame.word_wrap = False
        p0 = tb.text_frame.paragraphs[0]
        r0 = p0.add_run()
        r0.text = text
        r0.font.size = Pt(size)
        r0.font.name = latin
        pPr = p0._p.get_or_add_pPr()
        d = pPr.makeelement(qn("a:defRPr"), {})
        pPr.append(d)
        d.append(d.makeelement(qn("a:ea"), {"typeface": inherited}))
        return tb
    run = (text, size, dk.DEEP, False, False, latin) if ea is None \
        else (text, size, dk.DEEP, False, False, latin, ea)
    dk.text(s, 0.62, 2.0, 8.76, 0.4, [[run]], space_after=0, wrap=False)
    return list(s.shapes)[0]


def ink_w(text, latin="Helvetica Neue", ea=None, inherited=None, size=13):
    """The ink width _ink_rect measures for one un-wrapped run."""
    sh = _shape(text, latin, ea, inherited, size)
    r = dk._ink_rect(sh, dk._bbox_in(sh))
    return r[0][2] if r and r[0] else 0.0


def main():
    print("CJK measurement")

    # ---- the fix, stated as what it actually does: resolve the FACE ---------------------
    # This half is pure string resolution and holds on any machine, with or without the fonts.
    dk.FONT, dk.EAFONT = LAT, EA
    for label, kw, want in (
            ("the deck's EAFONT",              {},                      EA),
            ("an explicit 7th-slot ea face",   {"ea": "Songti SC"},     "Songti SC"),
            ("an INHERITED ea (para defRPr)",  {"inherited": "Songti SC"}, "Songti SC"),
    ):
        check("a CJK run is measured in %s, not <a:latin>" % label,
              face_of(CJK, **kw) == want, face_of(CJK, **kw))
    check("a LATIN run keeps <a:latin> (the untouched half)", face_of(LATIN) == LAT,
          face_of(LATIN))

    # ...and the width follows the face it resolved — the invariant that ties the two together,
    # true whether the font is installed (4.8750in) or substituted (DejaVu's number).
    w = ink_w(CJK)
    expect = dk._natural_width_in([(CJK, False)], 13, EA)
    check("the ink width IS the width of that face, not of the Latin one",
          abs(w - expect) < 0.02, "%.4f vs %.4f" % (w, expect))

    # ---- the inch values, only where a face that covers CJK exists ----------------------
    check_metric("a CJK run measures at its REAL width, not the Latin face's",
                 abs(w - TRUE_W) < 0.02, "%.4f vs %.4f" % (w, TRUE_W))
    check_metric("...which is ~1.86x what the old ruler reported (2.6181in)",
                 w > 4.0, "%.4f" % w)
    check_metric("an INHERITED ea face (paragraph defRPr) is honoured too",
                 abs(ink_w(CJK, inherited="Songti SC") - TRUE_W) < 0.02,
                 "%.4f" % ink_w(CJK, inherited="Songti SC"))
    check_metric("an explicit ea face in the run is honoured",
                 abs(ink_w(CJK, ea="Songti SC") - TRUE_W) < 0.02,
                 "%.4f" % ink_w(CJK, ea="Songti SC"))

    # ---- and the half that must not move ------------------------------------------------
    lat = ink_w(LATIN)
    check("a Latin run is measured exactly as before (no CJK, no change)",
          2.5 < lat < 4.5, "%.4f" % lat)
    check("a Latin run naming a CJK face still measures as Latin text",
          abs(ink_w(LATIN, latin="Songti SC") - ink_w(LATIN, latin="Songti SC")) < 1e-9)

    mixed_cjk = ink_w("认识 LUMC")
    mixed_lat = ink_w("LUMC")
    check("a mixed run is wider than its Latin part alone", mixed_cjk > mixed_lat,
          "%.3f vs %.3f" % (mixed_cjk, mixed_lat))

    # ---- the whole point: geometry decisions change ------------------------------------
    # A box that "fits" under the short ruler and overflows under the true one. This is the
    # defect class the fix exists for — under-measurement waves a real overflow through.
    dk.FONT, dk.EAFONT = "Helvetica Neue", "Hiragino Sans GB"
    prs = dk.blank_deck()
    s = dk.add_slide(prs)
    dk.box(s, 0, 0, 10, 5.625, fill=dk.RGBColor(0xFF, 0xFF, 0xFF))
    # 3.2in box holding 4.875in of CJK ink, with a visible outline so OVERFLOW can fire
    dk.box(s, 0.6, 2.0, 3.2, 0.42, fill=None, line=dk.RGBColor(0x88, 0x88, 0x88), line_w=1.0)
    dk.text(s, 0.6, 2.0, 3.2, 0.42, [[(CJK, 13, dk.DEEP, False, False, "Helvetica Neue")]],
            space_after=0, wrap=True)
    found = dk.lint_layout(prs, verbose=False)
    check_metric("CJK text overflowing its box is now measurable at all",
                 ink_w(CJK) > 3.2, "ink %.2f vs box 3.20" % ink_w(CJK))

    # ---- a real CJK deck must not suddenly light up ------------------------------------
    # The fix improves PRECISION; it must not act as a loosened or tightened threshold. A deck
    # that was clean under the short ruler and is genuinely well-built stays clean.
    dk.FONT, dk.EAFONT = "Helvetica Neue", "Hiragino Sans GB"
    prs = dk.blank_deck()
    for k in range(3):
        sl = dk.add_slide(prs)
        dk.text(sl, 0.62, 0.7, 8.76, 0.5,
                [[("认识 LUMC 医学中心", 23, dk.DEEP, True, False, "Helvetica Neue", "Songti SC")]],
                space_after=0, wrap=False)
        for j in range(3):
            dk.text(sl, 0.62, 1.6 + j * 0.34, 8.76, 0.26,
                    [[("一行普通的中文正文，长度适中，留有余量。", 12, dk.DEEP,
                       False, False, "Helvetica Neue")]], space_after=0, wrap=False)
    crit = [f for f in dk.lint_layout(prs, verbose=False) if f[1] == "CRITICAL"]
    check("a well-built CJK deck stays clean under the true ruler", crit == [], crit)

    _name_table_checks()

    if SKIP:
        print("\n  ({} width check(s) skipped: no CJK-covering font on this machine — the face-"
              "resolution checks above are the fix and they ran)".format(len(SKIP)))
    print("\n{} passed, {} failed".format(len(PASS), len(FAIL)))
    return 1 if FAIL else 0


def _probe_collection(path, faces):
    """Write a .ttc whose NAME TABLES register `faces` = [(family, style, advance of 一)].

    Built here so the resolver is tested on every runner: a CI box has neither PingFang nor
    Heiti, and a test that only runs where they exist tests the machine, not the code. Each face
    gives 一 a different advance, so a width says which face was actually loaded.
    """
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTCollection
    fonts = []
    for family, style, adv in faces:
        fb = FontBuilder(1000, isTTF=True)
        fb.setupGlyphOrder([".notdef", "uni4E00", "space"])
        fb.setupCharacterMap({0x4E00: "uni4E00", 0x20: "space"})
        pen = TTGlyphPen(None)
        pen.moveTo((40, 0)); pen.lineTo((40, 700)); pen.lineTo((adv - 40, 700))
        pen.lineTo((adv - 40, 0)); pen.closePath()
        empty = TTGlyphPen(None).glyph()
        fb.setupGlyf({".notdef": empty, "uni4E00": pen.glyph(), "space": empty})
        fb.setupHorizontalMetrics({".notdef": (500, 0), "uni4E00": (adv, 40), "space": (250, 0)})
        fb.setupHorizontalHeader(ascent=800, descent=-200)
        fb.setupNameTable({"familyName": family, "styleName": style,
                           "typographicFamily": family, "typographicSubfamily": style})
        fb.setupOS2(sTypoAscender=800, usWinAscent=800, usWinDescent=200)
        fb.setupPost()
        fonts.append(fb.font)
    coll = TTCollection()
    coll.fonts = fonts
    coll.save(str(path))


def _reset_font_caches():
    dk._NAME_INDEX = None
    for c in (dk._FONT_PATH_CACHE, dk._FONT_SUB_CACHE, dk._PIL_FONT_CACHE, dk._FACE_IDX_CACHE):
        c.clear()


def _name_table_checks():
    """A family registered only in a font file's NAME TABLE resolves, in the right face.

    🔴 matplotlib indexes one name per file. Measured on macOS: `STHeiti Light.ttc` registers
    "Heiti SC" (face 1) and is indexed as "STHeiti", and PingFang lives in an asset directory it
    never scans — so decks set in Heiti SC (five shipped presets) or PingFang SC measured every CJK
    line in DejaVu Sans, at 60% of its true width. LibreOffice, meanwhile, renders both faces
    correctly (verified by the fonts it embeds), so the ruler and the render disagreed.
    """
    import tempfile
    print("\n— a family known only by its font file's name table")
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="nametable-"))
    probe = tmp / "Probe.ttc"
    _probe_collection(probe, [("Zz Probe TC", "Regular", 1000),     # face 0
                              ("Zz Probe SC", "Regular", 700),      # face 1
                              ("Zz Probe SC", "Semibold", 900)])    # face 2 — no "Bold" exists
    real_extra = dk._extra_font_files
    dk._extra_font_files = lambda: [str(probe)]
    _reset_font_caches()
    try:
        def adv(name, bold=False):
            f = dk._pil_font(name, 10, bold)
            return round(f.getlength("一") / dk._MEAS_PREC / 10 * 1000)

        check("a family registered only in a name table is NOT a stand-in",
              dk._font_substituted("Zz Probe SC") is False, dk._font_substituted("Zz Probe SC"))
        check("...while a name registered nowhere still is",
              dk._font_substituted("Zz Probe Nowhere 9") is True)
        check("🔴 the REQUESTED family's face is measured — face 1, not the collection's face 0 "
              "(PingFang SC is face 3 of PingFang.ttc; Heiti SC face 1 of STHeiti Light.ttc)",
              adv("Zz Probe SC") == 700, adv("Zz Probe SC"))
        check("bold falls to the family's next HEAVIER face when it has no Bold (PingFang ships "
              "Semibold) — never back to Regular, which under-measures",
              adv("Zz Probe SC", True) == 900, adv("Zz Probe SC", True))
        check("the other family in the same file resolves to ITS face",
              adv("Zz Probe TC") == 1000, adv("Zz Probe TC"))
        check("a file whose faces do not name the family keeps the original rule (exact Regular "
              "anywhere, else face 0)",
              dk._face_index(str(probe), False, "Some Other Family") == 0
              and dk._face_index(str(probe), True, "Some Other Family") == 0)
        idx_obj = dk._NAME_INDEX
        dk._name_lookup("Zz Probe TC")
        check("the name-table index is built once per process, not per lookup",
              idx_obj is not None and dk._NAME_INDEX is idx_obj)

        out_sc, out_tc = tmp / "wm_sc.png", tmp / "wm_tc.png"
        dk.wordmark("一一一一", str(out_sc), font="Zz Probe SC", size=120)
        dk.wordmark("一一一一", str(out_tc), font="Zz Probe TC", size=120)
        from PIL import Image
        w_sc, w_tc = Image.open(out_sc).size[0], Image.open(out_tc).size[0]
        check("wordmark() draws in the requested family's face too (narrower SC face -> narrower "
              "mark)", w_sc < w_tc, (w_sc, w_tc))
    finally:
        dk._extra_font_files = real_extra
        _reset_font_caches()

    # a face matplotlib already knows must never pay for the scan
    _reset_font_caches()
    dk._font_file("DejaVu Sans")
    check("a face matplotlib resolves directly never builds the name-table index",
          dk._NAME_INDEX is None)

    # the live half: only where the real faces exist, and only then
    print("\n— live: the macOS faces that measured at 60% before this")
    truth = len(CJK) * 13 / 72.0
    for fam, reg, bold in (("PingFang SC", "Regular", "Semibold"), ("Heiti SC", "Light", "Medium")):
        if dk._font_substituted(fam):
            SKIP.append(fam)
            print("  skip %s is not installed on this machine" % fam)
            continue
        f = dk._pil_font(fam, 13)
        w = f.getlength(CJK) / dk._MEAS_PREC / 72.0
        check("%s measures CJK at its true width (%.4fin of %.4fin)" % (fam, w, truth),
              abs(w - truth) < 0.02, w)
        check("...regular in the %s face and bold in %s — the faces LibreOffice embeds for the "
              "same runs (PingFangSC-Regular/-Semibold, STHeitiSC-Light/-Medium, measured)"
              % (reg, bold),
              f.getname() == (fam, reg) and dk._pil_font(fam, 13, True).getname() == (fam, bold),
              (f.getname(), dk._pil_font(fam, 13, True).getname()))
    if not dk._font_substituted("Hiragino Sans GB"):
        import tempfile as _tf
        d = pathlib.Path(_tf.mkdtemp(prefix="wm-"))
        dk.wordmark("三扇门", str(d / "a.png"), font="Zz Nowhere Face 9", size=120)
        dk.wordmark("三扇门", str(d / "b.png"), font="Hiragino Sans GB", size=120)
        from PIL import Image, ImageChops
        same = ImageChops.difference(Image.open(d / "a.png").convert("RGBA"),
                                     Image.open(d / "b.png").convert("RGBA")).getbbox() is None
        check("🔴 a CJK wordmark whose face does not resolve falls back to a CJK face — it used to "
              "go straight to a Latin stand-in (tofu), because the fallback asked `is fp None` and "
              "_font_file never returns None", same)


if __name__ == "__main__":
    sys.exit(main())
