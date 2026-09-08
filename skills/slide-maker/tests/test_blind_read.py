#!/usr/bin/env python3
"""The blind read-back: the gate that reads the picture instead of the file.

The module carries its own `--selftest` (the comparison logic, exercised against the decks that
actually shipped broken). This file covers what that cannot: that the CONTRACT is wired into every
gate path identically, and that the properties which make the check meaningful — blindness,
computation, an answer owed — cannot be quietly satisfied.
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import blind_read as br  # noqa: E402

# 🔴 HERMETIC: point the taste ledger at a path that does not exist. It is USER-LEVEL data,
# so a test that reads the real one passes or fails by whatever the developer happens to
# have taught the skill — the same "passes by luck" class as a hash-salted fixture.
os.environ["SLIDE_MAKER_TASTE_LEDGER"] = "/nonexistent/taste-ledger-for-tests.json"

fails: list[str] = []


def check(cond, msg):
    if not cond:
        fails.append(msg)


# ── the module's own selftest must pass, and be reachable from here ──────────────────────────────
r = subprocess.run([sys.executable, str(SCRIPTS / "blind_read.py"), "--selftest"],
                   capture_output=True, text=True)
check(r.returncode == 0, "blind_read.py --selftest failed:\n{}{}".format(r.stdout, r.stderr))

# ── 🔴 THE SHARED CONTRACT. One module owns it; a per-gate copy is exactly the drift that
#    anchor_proof.py was created to stop, and that `png`/`path` reproduced afterwards. ───────────
for name in ("render_deck.py", "deck_gates.py", "codex_delivery_gate.py"):
    src = (SCRIPTS / name).read_text(encoding="utf-8")
    check("blind_read" in src, "{} does not consume the blind_read contract — a floor kept in one "
                               "runtime only is how the others stop enforcing it".format(name))
    check("taste_ledger" in src, "{} does not consume the taste ledger".format(name))
    # No gate may re-implement the vocabulary; it must import it.
    for token in ("READ_PLACEHOLDER", "READ_CONTRADICTION"):
        check(token not in src, "{} hard-codes `{}` instead of importing blind_read — that is a "
                                "second copy of the contract".format(name, token))

# ── blindness is structural: the packet must not leak the record ─────────────────────────────────
with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    (d / "render").mkdir()
    (d / "deck.pptx").write_bytes(b"x")
    for i in (1, 2, 3):
        p = d / "render" / "slide{:02d}.png".format(i)
        p.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 600)
        os.utime(p, (10 ** 9, 10 ** 9 + 500))          # newer than the pptx
    os.utime(d / "deck.pptx", (10 ** 9, 10 ** 9))
    (d / ".deck-gates.json").write_text(json.dumps({
        "content": {"slides": [{"slide": 1, "takeaway": "the secret takeaway nobody may see"}]},
        "design_plan": {"icon_family": "tabler"}}), encoding="utf-8")

    packet = br.build_packet(d)
    blob = json.dumps(packet, ensure_ascii=False)
    check("secret takeaway" not in blob,
          "the reader packet leaks the recorded takeaway — the read would not be blind")
    check("icon_family" not in blob and "tabler" not in blob,
          "the reader packet leaks the design plan — it would prime the element counts")
    check(len(packet["slides"]) == 3, "packet did not carry one entry per slide")
    check(len(packet["questions"]) == len(br.QUESTIONS), "packet dropped questions")

    # a STALE render must refuse loudly, not read the previous deck and call it fixed
    os.utime(d / "deck.pptx", (10 ** 9 + 9999, 10 ** 9 + 9999))
    try:
        br.build_packet(d)
        fails.append("a stale render was read instead of refused")
    except SystemExit as e:
        check("stale" in str(e).lower() or "older" in str(e).lower(),
              "the stale-render refusal does not say why: {}".format(e))

    # 🔴 a GAP in the numbering must refuse: the slide count is derived from the PNGs present, so a
    # missing slide02.png would make a 3-slide deck read as a 2-slide one and the coverage check
    # would pass with that page simply absent
    os.utime(d / "deck.pptx", (10 ** 9, 10 ** 9))
    (d / "render" / "slide02.png").unlink()
    try:
        br.build_packet(d)
        fails.append("a render with a missing middle slide was accepted — the deck would silently "
                     "shrink and the unrendered page would never be read")
    except SystemExit as e:
        check("missing" in str(e).lower() or "gap" in str(e).lower(),
              "the gap refusal does not say what is missing: {}".format(e))

    # no render at all → refuse, never silently pass
    for f in (d / "render").iterdir():
        f.unlink()
    try:
        br.build_packet(d)
        fails.append("a deck with no render did not refuse")
    except SystemExit:
        pass

# ── the properties that make it more than render_selfcheck ───────────────────────────────────────
QK = [k for k, _ in br.QUESTIONS]
one = dict({k: ([] if k in ("legible_text", "unreadable", "problems") else "x") for k in QK},
           n=1, elements={k: 0 for k in br.ELEMENT_KEYS})

# 1) it cannot be satisfied by asserting a verdict — there is no verdict field at all
check("verdict" not in QK, "the blind read grew a `verdict` field; a verdict is the thing "
                           "render_selfcheck already proves cannot be trusted")

# 2) findings must be ANSWERED, and `ok` is not an answer
unanswered = {"answers": [one], "findings": [{"n": 1, "code": "READ_CLIPPED", "severity": "hard",
                                              "finding": "footer clipped", "resolution": "ok"}]}
check(br.faults(unanswered, 1), "`ok` passed as the answer to a hard finding")

# 3) an absent comparison is distinguishable from a clean one
check(br.faults({"answers": [one]}, 1),
      "a record with answers but no `findings` passed — an absent comparison would look clean")
check(not br.faults({"answers": [one], "findings": []}, 1),
      "an empty findings list (a genuinely clean deck) was rejected")

# 4) the reader may be refuted with evidence, but not merely dismissed
base = {"n": 1, "code": "READ_CLIPPED", "severity": "hard", "finding": "x",
        "resolution": "checked this one carefully at full size"}
check(br.faults({"answers": [one], "findings": [dict(base)]}, 1),
      "a hard finding with neither `fixed` nor `refuted` passed")
check(not br.faults({"answers": [one],
                     "findings": [dict(base, refuted="re-read the PNG; nothing is clipped")]}, 1),
      "a refuted hard finding was rejected — the reader is not infallible and must be answerable")

# 5) a carve is a claim about the deck, not an escape hatch
check(br.waiver_faults({"waived": "x", "waived_category": "no-reader"}),
      "a carve with a token reason passed")
check(not br.waiver_faults({"waived": "this runtime has no independent reader available",
                            "waived_category": "no-reader"}),
      "a properly claimed `no-reader` carve was rejected")
check("no-reader" in br.CARVES,
      "there is no way to record that a deck shipped UNREAD — runtimes without a reader would have "
      "to claim it was read")

# ── generality: the checks must not be Latin-only ────────────────────────────────────────────────
check(br.tokens("出发前先订好轮渡"), "the tokenizer returns nothing for Chinese — every CJK deck "
                                      "would score zero overlap and fire on every slide")
check(br.overlap("出发前先订好轮渡票", "出发前先订好轮渡") > 0.5,
      "CJK overlap is not measured; a Chinese deck cannot pass the claim check")
for cn, want in (("页脚文字被切掉", "READ_CLIPPED"), ("页码和正文重叠", "READ_OVERLAP"),
                 ("标题和正文矛盾", "READ_CONTRADICTION"), ("序号太小看不清", "READ_LEGIBILITY")):
    got = br.classify_problem(cn)
    check(got and got[0] == want,
          "Chinese problem {!r} triaged as {} — a CJK deck would report all-taste".format(cn, got))

# ── determinism: no hash-salted anything (this repo has shipped that bug once) ────────────────────
runs = {json.dumps([f["code"] for f in br.compare([one], total=1)]) for _ in range(5)}
check(len(runs) == 1, "compare() is not deterministic across runs")

# ── no direct shape.name-style bypass: nothing may write findings without the comparator ─────────
src = (SCRIPTS / "blind_read.py").read_text(encoding="utf-8")
tree = ast.parse(src)
sev_literals = {n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value in ("hard", "ask", "note")}
check({"hard", "ask", "note"} <= sev_literals, "the three severities are not all used")

print("\n".join("FAIL " + f for f in fails) if fails else "", end="")
print("[test_blind_read] {}".format("FAILED: {} problem(s)".format(len(fails)) if fails else "ok"))
sys.exit(1 if fails else 0)
