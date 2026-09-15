#!/usr/bin/env python3
"""A registry of DECK PURPOSES — and the content each genre is not finished without.

🔴 WHY THIS EXISTS. `references/design-by-purpose.md` carries nine purposes, each a prose recipe
(Type · Palette · Density · Layout · Icons · Signature). Measured by grep, NOTHING consumed it: a
purpose entry could be ignored line by line and no gate would know, so every per-purpose rule in
that file was advisory by construction. And four genres with the hardest conventions were absent
from the list entirely — a grant proposal, a progress/guidance committee, a journal club, and a
clinical case presentation. The last three are among the most common decks an academic makes.

The mechanism is deliberately the SAME ONE `formats.py` already uses for surfaces: a registry
declares the sections a genre cannot be finished without, and `check_purpose.py` looks for them in
the built deck. That precedent exists because of a real finding — "a poster in the billboard style
that reads best is also the style that drops the two things a passer-by cannot reconstruct" — and
the finding generalises: the shape of a genre is exactly what an author under time pressure drops.

🔴 WHAT THIS CHECK IS, AND IS NOT. It asks "does this deck NAME the thing", not "does it do it
well". A deck can name its risks in two words and pass; judging whether the mitigation is credible
is the critic's job and always will be. The cheap catch is the one worth having: a grant deck with
no feasibility slide and a committee deck with no ask are not weak decks, they are decks missing a
section their audience is required to score.

Synonyms are multilingual on purpose — a 中文 deck names the same section in 中文, and a check that
only knows English would fire on every one of them.

    python3 scripts/purposes.py --list
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Purpose:
    name: str
    label: str
    note: str
    # (section label, (term, term, …)) — the deck must NAME each section somewhere
    required_sections: tuple = field(default_factory=tuple)
    # words in the user's recorded purpose/goal that bind a deck to this entry
    binds_on: tuple = field(default_factory=tuple)
    # the one fidelity rule this genre carries beyond the universal never-invent floor
    fidelity: str = ""


PURPOSES = (
    Purpose(
        "grant", "Grant proposal / funding pitch",
        "ERC · NWO · NIH · Horizon — the highest-stakes deck an academic makes, and the one with "
        "the most rigid conventions, because reviewers score against named criteria.",
        # 🔴 No bare "proposal": a business proposal, a project proposal and a marriage proposal
        # are not this genre, and `recorded_purpose` also reads the AUDIENCE BRIEF, so a loose term
        # binds far more decks than the purpose row alone would.
        binds_on=("grant proposal", "research proposal", "grant application", "grant", "funding",
                  "fellowship", "erc ", "nwo", "nih ", "horizon europe",
                  "基金", "课题申请", "项目申请", "经费申请"),
        required_sections=(
            ("aims", ("aim", "aims", "objective", "objectives", "research question", "goal of this",
                      "what i propose", "目标", "研究目标", "科学问题")),
            ("feasibility", ("feasib", "track record", "preliminary", "pilot data", "why me",
                             "why now", "capability", "expertise", "可行性", "前期", "预研")),
            ("risk", ("risk", "risks", "mitigation", "contingency", "fallback", "what could go "
                      "wrong", "风险", "应对", "备选")),
        ),
        fidelity="Preliminary data is the section most often overstated. A pilot is a pilot: say n, "
                 "say it is preliminary, and never let a promising trend read as an established "
                 "result — a reviewer who catches one inflated claim discounts the rest.",
    ),
    Purpose(
        "committee", "Progress / guidance committee meeting",
        "A PhD guidance committee, a thesis advisory board, a stage-gate review. It differs from a "
        "lab meeting in exactly one way, and it is the way that matters: the room has to DECIDE "
        "something — is this on track, does the book hold together, what should be scoped down.",
        # 🔴 No bare "committee" or "advisory": an INVESTMENT committee, an ETHICS committee and a
        # steering committee are different genres with different required content, and binding them
        # here would fire a three-section list at the wrong deck — which is how a check teaches
        # people to ignore it. The qualifier is what makes the binding a claim rather than a guess.
        binds_on=("guidance committee", "advisory committee", "thesis committee",
                  "doctoral committee", "supervisory committee", "committee meeting",
                  "progress review", "annual review", "progress meeting", "stage gate", "go/no-go",
                  "指导委员会", "中期考核", "年度考核", "开题", "进展汇报"),
        required_sections=(
            ("progress", ("progress", "since last", "this year", "past year", "completed",
                          "published", "achieved", "进展", "已完成", "去年")),
            ("plan", ("plan", "next", "remaining", "timeline", "roadmap", "schedule", "ahead",
                      "计划", "下一步", "时间线", "剩余")),
            ("ask", ("advice", "guidance", "decision", "question", "input", "feedback",
                     "recommend", "建议", "决策", "请教", "问题")),
        ),
        fidelity="What is NOT done yet must read as not done. A committee's value is advice on open "
                 "work, and a hypothesis promoted to a result removes the very thing they are "
                 "there to help with (`content.open_ledger` is the artifact for this).",
    ),
    Purpose(
        "journal_club", "Journal club / presenting someone else's paper",
        "You are presenting work you did not do. Extremely common, and it carries a fidelity risk "
        "the universal never-invent rule does not cover: not fabrication, but MISATTRIBUTION — "
        "stating their result more strongly than they did, or blurring their claims with your "
        "critique until the audience cannot tell which is which.",
        binds_on=("journal club", "paper presentation", "reading group", "present a paper",
                  "discuss the paper", "文献汇报", "文献阅读", "组会读论文", "论文分享", "读书会"),
        required_sections=(
            ("attribution", ("et al", "authors", "published in", "doi", "arxiv", "reference",
                             "citation", "source", "作者", "发表于", "文献")),
            ("critique", ("limitation", "limitations", "weakness", "critique", "caveat",
                          "my take", "assessment", "concerns", "局限", "不足", "评价", "批评")),
        ),
        fidelity="Keep THEIR claim and YOUR reading visually separable — attribute on the slide "
                 "that carries the result, not only on the title. An audience that cannot tell "
                 "which is which will remember your critique as the paper's own conclusion.",
    ),
    Purpose(
        "clinical_case", "Clinical case presentation / tumour board / M&M",
        "A fixed clinical narrative — presentation, investigations, management, outcome. The "
        "structure is not a style choice: colleagues are being asked to judge a decision, and they "
        "cannot do that without the information that was available when it was made.",
        binds_on=("case presentation", "clinical case", "tumour board", "tumor board", "mdt",
                  "morbidity", "mortality", "m&m", "grand round", "病例", "疑难病例", "多学科",
                  "查房"),
        required_sections=(
            ("presentation", ("history", "presented", "presentation", "symptom", "chief complaint",
                              "病史", "主诉", "现病史")),
            ("investigations", ("imaging", "investigation", "workup", "work-up", "laboratory",
                                "labs", "biopsy", "scan", "ct", "mri", "检查", "影像", "化验")),
            ("management", ("management", "treatment", "plan", "intervention", "therapy",
                            "operation", "治疗", "处理", "方案")),
            ("outcome", ("outcome", "follow-up", "follow up", "learning point", "take-home",
                         "what we learned", "转归", "随访", "经验", "教训")),
        ),
        fidelity="🔴 DE-IDENTIFICATION IS LOAD-BEARING HERE, not a nicety — this is the genre "
                 "PRE-FLIGHT 5's burned-in-identifier check exists for. Name, MRN, accession, date "
                 "of birth, study date and institution on any scan, read on all four edges and in "
                 "every overlay strip. Get a de-identified export; never crop or blur and ship.",
    ),
)

BY_NAME = {p.name: p for p in PURPOSES}


def match(recorded: str):
    """The Purpose a recorded purpose/goal string binds to, or None.

    Substring matching on the USER's own words, because that is all a record carries. Deliberately
    conservative: no match means NOT CHECKED, never a guessed genre — applying a clinical-case
    section list to a product pitch would be worse than checking nothing.
    """
    if not recorded:
        return None
    blob = str(recorded).lower()
    best = None
    for p in PURPOSES:
        for term in p.binds_on:
            if term in blob:
                # longest term wins: "progress review" should beat a bare "review" elsewhere
                if best is None or len(term) > best[0]:
                    best = (len(term), p)
    return best[1] if best else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--match", default=None, help="show which purpose a recorded string binds to")
    a = ap.parse_args(argv)
    if a.match is not None:
        p = match(a.match)
        print("%r -> %s" % (a.match, p.name if p else "no purpose bound (NOT CHECKED)"))
        return 0
    for p in PURPOSES:
        print("%-14s %s" % (p.name, p.label))
        print("               %s" % p.note)
        print("               requires: %s" % ", ".join(lbl for lbl, _t in p.required_sections))
        print("               binds on: %s" % ", ".join(p.binds_on[:6]))
        if p.fidelity:
            print("               fidelity: %s" % p.fidelity.split(".")[0])
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
