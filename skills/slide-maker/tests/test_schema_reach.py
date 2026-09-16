#!/usr/bin/env python3
"""A gate that CALLS a checker on both runtimes can still be unable to READ either one's record.

🔴 THE FAILURE THIS EXISTS FOR, measured. `check_purpose` was wired into both gate paths and
`check_gate_parity` reported 21 sections, 0 problems — correctly, by its own definition: it checks
that each `_gate_section` is *reachable* in `codex_delivery_gate.py`, and it was. But the extractor
read `design.purpose`, and inspecting the REAL scaffold that `codex_delivery_gate.py --init` writes
showed the Codex schema has no `purpose` key anywhere — not top level, not under `design`. The gate
existed on that runtime and could almost never bind. Parity was green the whole time.

That hole is structural, not a one-off: parity compares FILES, and this compares BEHAVIOUR. Split
by hand across the two paths, the reads that could carry it are

    shared  25 record reads — 19 are waiver lookups, 6 FEED a check
    codex   42 record reads — 11 are waiver lookups, 31 FEED a check

and the dangerous ones are the FEEDING reads' nested paths, because the top-level keys (`design`,
`interview`, `content`) do exist in both scaffolds. A static scan cannot settle this: the extractor
that failed loops over a tuple of candidate key names, which no regex reads.

So each extractor here is run against a PLAUSIBLY FILLED record for BOTH runtimes, filled the way
that runtime actually fills it, and must find what it needs on both. A `NOT CHECKED` that nobody
can ever clear is indistinguishable from a passing gate, which is the whole failure class.

Run: python3 tests/test_schema_reach.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
SCRIPTS = os.path.join(SKILL, "scripts")
sys.path.insert(0, SCRIPTS)

OK, BAD = [], []


def ck(cond, msg):
    (OK if cond else BAD).append(msg)
    print(("  ok   " if cond else "  ✗    ") + msg)


def shared_scaffold():
    """The real `.deck-gates.json` skeleton, from the tool that writes it."""
    d = tempfile.mkdtemp(prefix="reach-shared-")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "deck_gates.py"), "init", d,
                    "--slides", "3"], capture_output=True, text=True, check=True)
    return json.load(open(os.path.join(d, ".deck-gates.json")))


def codex_scaffold():
    """The real Codex evidence skeleton, from the tool that writes it."""
    f = os.path.join(tempfile.mkdtemp(prefix="reach-codex-"), "ev.json")
    subprocess.run([sys.executable, os.path.join(SCRIPTS, "codex_delivery_gate.py"), "--init", f],
                   capture_output=True, text=True, check=True)
    return json.load(open(f))


print("— both scaffolds come from the tools that really write them, not from a copy here")
SH, CX = shared_scaffold(), codex_scaffold()
ck(isinstance(SH, dict) and isinstance(CX, dict), "both scaffolds load")
ck("interview" in SH and "interview" in CX, "both carry an `interview` block")
ck("purpose" not in CX and "purpose" not in (CX.get("design") or {}),
   "🔴 the Codex schema still has NO `purpose` key — the fact that made the purpose gate unbindable "
   "there. If this ever flips, the extractor can be simplified; until then it must not depend on it")

print("\n— PURPOSE: the extractor must find the genre on a record from EITHER runtime")
import check_purpose as cp                                                # noqa: E402
import purposes                                                           # noqa: E402

# filled the way each runtime actually fills it — the shared path records a purpose PICK, the Codex
# path (supervised) records the user's words in `interview.record` and an audience brief.
sh = json.loads(json.dumps(SH))
sh["interview"]["picks"] = [{"axis": "purpose", "source": "stated",
                             "value": "PhD guidance committee meeting"}]
cx = json.loads(json.dumps(CX))
cx["interview"]["record"] = "the user asked for a guidance committee meeting deck"
cx["content"]["audience_brief"] = {"who": "the PhD guidance committee",
                                   "decisions": [{"decision": "is the thesis on track"}]}
for rec, label in ((sh, "shared .deck-gates.json"), (cx, "Codex evidence")):
    got = purposes.match(cp.recorded_purpose(rec))
    ck(got is not None and got.name == "committee",
       "%s -> the purpose extractor binds (%s)" % (label, got.name if got else "NOTHING"))

# …and an UNFILLED scaffold must still bind to nothing on both, or the gate fires at placeholders
for rec, label in ((SH, "shared"), (CX, "Codex")):
    ck(purposes.match(cp.recorded_purpose(rec)) is None,
       "an unfilled %s scaffold binds to NOTHING — placeholder text is not a genre" % label)

print("\n— AUDIENCE BRIEF: the shared contract must read both schemas")
import audience_brief as ab                                               # noqa: E402
# the contract requires >=3 decisions ("fewer than that is a persona, not a brief") — the first
# fixture here had one and the suite reported the CONTRACT as broken. The contract was right.
good = {"who": "the PhD guidance committee, deciding whether the thesis is on track",
        "decisions": [{"decision": "is it on track", "needs": "the status of every chapter"},
                      {"decision": "does the thesis hold together",
                       "needs": "the line of enquiry, shown not asserted"},
                      {"decision": "what to scope down", "needs": "what is actually left"}]}
for rec_name, rec in (("shared", {"content": {"audience_brief": good}}),
                      ("Codex", {"content": {"audience_brief": good}})):
    faults = ab.faults(good)
    ck(faults == [], "%s: a filled audience brief passes its own contract (%r)" % (rec_name, faults))
ck(ab.faults({"who": "", "decisions": []}) != [],
   "…and an empty one does not — the contract is not vacuous")

print("\n— DELEGATED PICKS: auto-mode detection must work off each runtime's checkpoint shape")
import delegated_picks as dp                                              # noqa: E402
for label, rec in (("shared", {"content": {"checkpoint": {"mode": "auto"}},
                               "design_plan": {"checkpoint": {"mode": "auto"}}}),
                   ("Codex", {"content": {"checkpoint": {"mode": "auto"}},
                              "design": {"checkpoint": {"mode": "auto"}}})):
    ck(dp.is_auto(rec) is True,
       "%s: an auto-waiver deck is detected, so the delegated-picks record is demanded there" % label)
for label, rec in (("shared", {"content": {"checkpoint": {"mode": "approved"}},
                               "design_plan": {"checkpoint": {"mode": "approved"}}}),
                   ("Codex", {"content": {"checkpoint": {"mode": "approved"}},
                              "design": {"checkpoint": {"mode": "approved"}}})):
    ck(dp.is_auto(rec) is False,
       "%s: a supervised deck is NOT treated as auto — it records nothing extra" % label)

print("\n— ANCHOR PROOF: the record shape differs between the runtimes by spelling")
import anchor_proof as ap                                                 # noqa: E402
ck(ap.anchor_file({"role": "signature", "slide": 4, "png": "render/slide04.png"}) is not None,
   "the shared spelling (`png`) resolves")
ck(ap.anchor_file({"role": "signature", "slide": 4, "path": "render/slide04.png"}) is not None,
   "the Codex spelling (`path`) resolves — this pair is why the contract module exists at all")

print("\n— SURFACE: the section TERMS extension must be reachable under each schema's design key")
# the feeding read is `surface_section_terms` — the author's escape for a field's own vocabulary.
# It lives under `design_plan` on the shared path and `design` on the Codex one, which is exactly
# the pair that has already drifted twice in this repo.
for label, rec, key in (("shared", {"design_plan": {"surface_section_terms": {"methods": ["方法"]}}},
                         "design_plan"),
                        ("Codex", {"design": {"surface_section_terms": {"methods": ["方法"]}}},
                         "design")):
    got = (rec.get(key) or {}).get("surface_section_terms")
    ck(got == {"methods": ["方法"]},
       "%s: surface_section_terms is reachable under %r" % (label, key))
ck((SH.get("design_plan") is not None) and (CX.get("design") is not None),
   "…and BOTH scaffolds carry the design block those terms hang off "
   "(shared `design_plan`, Codex `design`)")

print("\n— CHECKPOINTS (checkpoints): auto-vs-approved must be readable from both, or delegation is invisible")
for label, rec in (("shared", SH), ("Codex", CX)):
    c = (rec.get("content") or {}).get("checkpoint")
    d = (rec.get("design_plan") or rec.get("design") or {}).get("checkpoint")
    ck(isinstance(c, dict) and "mode" in c and isinstance(d, dict) and "mode" in d,
       "%s: content.checkpoint.mode AND the design checkpoint's mode both exist in the real "
       "scaffold — a delegated run and a skipped one must not look identical" % label)

print("\n— CONTENT.AUDIENCE_BRIEF: covered above, and its contract is not vacuous")
ck(ab.faults(good) == [] and ab.faults({"who": "", "decisions": []}) != [],
   "content.audience_brief passes when filled and fails when empty, from the ONE shared contract "
   "module both paths import")

print("\n— the loop is closed: every record-FED gate section is covered here")
import re                                                                 # noqa: E402
import check_gate_parity as gp                                            # noqa: E402
covered = open(os.path.join(HERE, "test_schema_reach.py")).read()
for name in gp.RECORD_FED:
    ck(name.upper().replace("_", " ") in covered or name in covered,
       "gate section %r is exercised by this suite" % name)

print()
print("%d passed, %d failed" % (len(OK), len(BAD)))
raise SystemExit(1 if BAD else 0)
