#!/usr/bin/env python3
"""
Cover-letter agent.

Three-pass architecture:
  1. Implementer  — drafts a tailored letter from the JD + knowledge files
  2. Auditor      — critiques the draft against voice principles
  3. Polisher     — produces the final, addressing every critique point

Usage:
    python apply.py postings/some-job.txt
    cat job.txt | python apply.py -
"""

import argparse
import os
import re
import sys
from datetime import date
from pathlib import Path

try:
    from anthropic import Anthropic
except ImportError:
    sys.exit("Missing dependency. Run: pip install -r requirements.txt")

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # .env is optional if the user exports the key another way


ROOT = Path(__file__).resolve().parent
KNOWLEDGE_DIR = ROOT / "knowledge"
LETTERS_DIR = ROOT / "letters"
MODEL = os.environ.get("MODEL", "claude-sonnet-4-6")
MAX_TOKENS = 4096


def load_knowledge() -> dict[str, str]:
    return {
        "resume": (KNOWLEDGE_DIR / "resume.md").read_text(),
        "voice": (KNOWLEDGE_DIR / "voice.md").read_text(),
        "story": (KNOWLEDGE_DIR / "story.md").read_text(),
    }


def read_posting(path_or_stdin: str) -> str:
    if path_or_stdin == "-":
        return sys.stdin.read()
    return Path(path_or_stdin).read_text()


def strip_em_dashes(text: str) -> str:
    """Hard guarantee: no em-dash ever reaches the deliverable, regardless of what
    the model produced. The prompts forbid them; this is the deterministic backstop.
    Converts both em-dashes (—) and en-dashes (–) used as punctuation into clean
    sentence punctuation."""
    # Spaced dash acting as a clause joiner -> comma.
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    # Clean up artifacts: ", ," -> ",", space-before-comma, doubled spaces.
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


def parse_contact() -> dict[str, str]:
    """Pull name + contact fields from the '## Header' block of resume.md so the
    PDF letterhead stays in sync with the resume rather than being hardcoded."""
    resume = (KNOWLEDGE_DIR / "resume.md").read_text()
    fields: dict[str, str] = {}
    # First markdown H1 is the candidate's name (e.g. "# Ting Geidel — Resume content").
    h1 = re.search(r"^#\s+(.+)$", resume, re.MULTILINE)
    if h1:
        fields["name"] = h1.group(1).split("—")[0].strip()
    # Bulleted "**Key:** value" lines under the header.
    for key in ("Location", "Phone", "Email", "LinkedIn", "GitHub"):
        m = re.search(rf"\*\*{key}:\*\*\s*(.+)", resume)
        if m:
            fields[key.lower()] = m.group(1).strip()
    return fields


def slugify(text: str, max_len: int = 60) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text[:max_len] or "untitled"


def call_claude(client: Anthropic, system: str, user: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


def identify_company_and_role(client: Anthropic, posting: str) -> tuple[str, str]:
    """Extract company name and role title from the posting for filename + opener."""
    system = (
        "You extract structured info from job postings. "
        "Respond in exactly two lines:\n"
        "COMPANY: <name>\n"
        "ROLE: <title>\n"
        "Nothing else. No preamble. If unclear, give your best guess."
    )
    raw = call_claude(client, system, posting)
    company, role = "unknown-company", "unknown-role"
    for line in raw.splitlines():
        if line.startswith("COMPANY:"):
            company = line.split(":", 1)[1].strip()
        elif line.startswith("ROLE:"):
            role = line.split(":", 1)[1].strip()
    return company, role


def implementer_prompt(k: dict[str, str], company: str, role: str) -> str:
    return f"""You are drafting a cover letter on behalf of Ting Geidel.

You have three sources of ground truth:

<resume>
{k['resume']}
</resume>

<voice>
{k['voice']}
</voice>

<story>
{k['story']}
</story>

Target: {role} at {company}.

You will receive the job posting in the next message. Read it carefully. Then write a tailored cover letter that follows the four-paragraph structure in <voice>.

Hard rules:
- Do not fabricate any claim, number, or experience not present in <resume>.
- Every factual claim about Ting's history must come from <resume>. Use <story> ONLY for motivation (why she does this work, what she's looking for). Never lift a biographical fact or a pre-written personality line from <story> into the letter.
- Write plainly. The letter must sound like a real person talking to a hiring manager, not like polished marketing copy. Do not insert crafted self-characterizations meant to sound memorable. If a sentence sounds impressive read aloud, make it plainer. Understated and specific beats quotable.
- Do not invent any fact about {company} not present in the job posting you will receive. See the "Hard prohibition on fabrication" section of <voice>. This includes blog posts, engineering posts, customer names, product features, quotes, values, or announcements not in the JD.
- If paragraph 3 needs a "why this company" anchor and the JD gives you no specific signal, use the company's own "About" description from the JD, or match a JD-stated responsibility to a piece of my experience. Do not invent external references.
- Do not include any pattern listed in the "Patterns to avoid" section of <voice>.
- ZERO em-dashes. Do not use the "—" character anywhere. Use periods, commas, colons, or parentheses instead. This is non-negotiable.
- Never offer to demo, screen-share, or walk through the actual AZL systems, agents, or dashboards. They are confidential. You may state at a high level what was built and the result, but the close must not offer to show internal systems.
- Stay within 280-350 words.
- Output the letter only. No header, no signature block, no commentary.
- Do not write a salutation ("Dear hiring manager"). Start with the first paragraph directly.
"""


def auditor_prompt(k: dict[str, str], company: str, role: str, draft: str, posting: str) -> str:
    return f"""You are a brutally honest reviewer of Ting Geidel's cover letter draft.

The voice principles she writes by:

<voice>
{k['voice']}
</voice>

Her resume (ground truth — flag any claim in the draft that exceeds it):

<resume>
{k['resume']}
</resume>

The original job posting (ground truth for any company-specific claim):

<jd>
{posting}
</jd>

Target: {role} at {company}.

Here is the draft:

<draft>
{draft}
</draft>

Produce a numbered critique with these checks. For each item, quote the offending phrase from the draft and explain why it fails.

1. AI-tells — any rule-of-three, rule-of-four, rhetorical contrast, aphoristic finisher, buzzword salad, generic enthusiasm, hedge phrase, or em-dash overuse?
2. Specificity — does paragraph 2 carry a real number or named-tool detail? Could any sentence appear in another candidate's letter unchanged?
3. JD signal coverage — what specific asks from the JD does the draft fail to address?
4. Fabrication check — flag ANY claim about {company} that you cannot locate in the JD text or in <resume>. This includes references to blog posts, engineering posts, customer names, product features, executive quotes, stated values, or announcements. Quote each suspect phrase. The default assumption is fabrication; the draft must prove the claim is grounded.
5. "Why them" test — does paragraph 3 reference something only someone who looked at THIS company's JD could write? Or is it generic?
6. Closer — is the close a small offer or a generic request?
7. Word count — count the words. Report it. Within 280-350?

End with a "PRIORITY FIXES" section listing the 3-5 highest-impact changes for the polisher.

CRITICAL: If a PRIORITY FIX asks the polisher to "add a real signal" or "reference something specific about the company," you must also tell the polisher WHERE to find that signal — either quote a specific line from the JD they should anchor on, or instruct them to write a shorter, JD-internal paragraph instead. Never tell the polisher to find a signal that isn't already in the context — that pushes them to fabricate.

Be surgical. Quote exact phrases. Do not soften.
"""


def polisher_prompt(k: dict[str, str], company: str, role: str, draft: str, critique: str, posting: str) -> str:
    return f"""You are polishing Ting Geidel's cover letter to its final form.

Voice principles:

<voice>
{k['voice']}
</voice>

Resume (ground truth):

<resume>
{k['resume']}
</resume>

Original job posting (ground truth for any company-specific claim):

<jd>
{posting}
</jd>

Target: {role} at {company}.

Original draft:

<draft>
{draft}
</draft>

Critique to address:

<critique>
{critique}
</critique>

Produce the final cover letter. Address every PRIORITY FIX. Keep what was working. Do not introduce new AI-tells while fixing old ones. Stay within 280-350 words.

ZERO em-dashes. The final letter must not contain the "—" character even once. Replace every em-dash with a period, comma, colon, or parentheses, or restructure the sentence. Re-read the finished letter and confirm there are none before producing it.

Never offer to demo, screen-share, or walk through the actual AZL systems, agents, or dashboards. They are confidential employer property. The close may offer to talk through how Ting would approach the role, or to walk through her own project (Wren), but never AZL internals.

CRITICAL: You may NOT introduce any new specific claim about {company} that isn't already grounded in the JD text or in <resume>. If the critique tells you to "find a real signal" or "reference something specific about the company," do not invent a blog post, engineering write-up, customer name, product feature, executive quote, or value statement. Instead, anchor paragraph 3 in:
- the company's own "About" description from the JD,
- a specific JD-stated responsibility you can match to <resume>,
- or a shorter paragraph that uses only JD-internal material.

A shorter, honest paragraph 3 is strictly better than a longer paragraph 3 that fabricates company-specific detail. Fabricated specifics end candidacies in interview.

Output the letter only — no header, no signature, no commentary. No salutation; start with the first paragraph.
"""


def render_pdf(letter: str, contact: dict[str, str], out_path: Path) -> bool:
    """Render the letter to a clean, submission-ready PDF with a name/contact
    letterhead. Returns False if reportlab isn't installed so the caller can
    fall back to a plain-text deliverable."""
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import letter as LETTER_SIZE
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import inch
        from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer
    except ImportError:
        return False
    from html import escape

    INK, GREY, RULE = HexColor("#1a1a1a"), HexColor("#555555"), HexColor("#cfcfcf")
    name = contact.get("name", "")
    # Two contact rows, matching the resume letterhead format (" • " separators).
    # Strip any parenthetical from location (e.g. "(open to remote)") for the letterhead.
    contact = dict(contact)
    if contact.get("location"):
        contact["location"] = re.sub(r"\s*\(.*?\)", "", contact["location"]).strip()
    row1 = " • ".join(contact[k] for k in ("location", "phone", "email") if contact.get(k))
    row2 = " • ".join(contact[k] for k in ("linkedin", "github") if contact.get(k))

    name_style = ParagraphStyle("Name", fontName="Helvetica-Bold", fontSize=18,
                                leading=21, textColor=INK, spaceAfter=3)
    meta_style = ParagraphStyle("Meta", fontName="Helvetica", fontSize=8.7,
                                leading=12.5, textColor=GREY)
    date_style = ParagraphStyle("Date", fontName="Helvetica", fontSize=10,
                                leading=14, textColor=GREY)
    body_style = ParagraphStyle("Body", fontName="Helvetica", fontSize=10.5,
                                leading=16, alignment=TA_LEFT, textColor=INK,
                                spaceAfter=11)
    sign_style = ParagraphStyle("Sign", fontName="Helvetica-Bold", fontSize=10.5,
                                leading=14, textColor=INK)

    flow = []
    if name:
        flow.append(Paragraph(escape(name), name_style))
    for row in (row1, row2):
        if row:
            flow.append(Paragraph(escape(row), meta_style))
    flow.append(Spacer(1, 9))
    flow.append(HRFlowable(width="100%", thickness=0.75, color=RULE,
                           spaceBefore=0, spaceAfter=18))
    flow.append(Paragraph(date.today().strftime("%B %-d, %Y"), date_style))
    flow.append(Spacer(1, 16))

    for para in (p.strip() for p in letter.split("\n\n")):
        if para:
            flow.append(Paragraph(escape(para).replace("\n", " "), body_style))

    flow.append(Spacer(1, 6))
    flow.append(Paragraph("Sincerely,", body_style))
    flow.append(Spacer(1, 2))
    flow.append(Paragraph(escape(name), sign_style))

    SimpleDocTemplate(
        str(out_path), pagesize=LETTER_SIZE,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        leftMargin=1.1 * inch, rightMargin=1.1 * inch,
        title=f"Cover letter — {name}",
    ).build(flow)
    return True


def run(posting_path: str) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit(
            "Missing ANTHROPIC_API_KEY. Copy .env.example to .env and add your key "
            "(get one at https://console.anthropic.com)."
        )

    client = Anthropic(api_key=api_key)
    knowledge = load_knowledge()
    posting = read_posting(posting_path)

    print("Reading job posting…", file=sys.stderr)
    company, role = identify_company_and_role(client, posting)
    print(f"  Company: {company}", file=sys.stderr)
    print(f"  Role:    {role}", file=sys.stderr)

    print("Drafting cover letter…", file=sys.stderr)
    draft = call_claude(client, implementer_prompt(knowledge, company, role), posting)

    print("Critique pass (checking voice, fabrication, JD coverage)…", file=sys.stderr)
    critique = call_claude(
        client,
        auditor_prompt(knowledge, company, role, draft, posting),
        "Produce the critique now, following the numbered structure.",
    )

    print("Polishing…", file=sys.stderr)
    final = call_claude(
        client,
        polisher_prompt(knowledge, company, role, draft, critique, posting),
        "Produce the final cover letter now.",
    )
    final = strip_em_dashes(final)  # deterministic backstop; the prompts already forbid them

    LETTERS_DIR.mkdir(exist_ok=True)
    slug = f"{date.today().isoformat()}-{slugify(company)}-{slugify(role)}"
    out_pdf = LETTERS_DIR / f"{slug}.pdf"
    out_critique = LETTERS_DIR / f"{slug}.critique.md"

    # The critique log is diagnostics, not the deliverable — keep it in a sidecar file.
    out_critique.write_text(
        f"# Critique log — {company} ({role})\n\n"
        f"Generated {date.today().isoformat()} by cover-letter-agent.\n\n"
        f"{critique}\n"
    )

    print("Rendering PDF…", file=sys.stderr)
    if render_pdf(final, parse_contact(), out_pdf):
        deliverable = out_pdf
    else:
        # reportlab missing — fall back to a clean plain-text letter so the run still produces something usable.
        deliverable = LETTERS_DIR / f"{slug}.txt"
        deliverable.write_text(final + "\n")
        print("  reportlab not installed — wrote .txt instead (pip install -r requirements.txt for PDF)",
              file=sys.stderr)

    print(f"\n✓ {deliverable}", file=sys.stderr)
    print(f"  critique: {out_critique}", file=sys.stderr)
    print(file=sys.stderr)
    print(final)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a tailored cover letter from a job posting.")
    parser.add_argument("posting", help="Path to a text file with the JD, or '-' to read from stdin.")
    args = parser.parse_args()
    run(args.posting)


if __name__ == "__main__":
    main()
