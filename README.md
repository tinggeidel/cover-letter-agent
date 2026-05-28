# cover-letter-agent

A small CLI tool that turns a job posting into a tailored cover letter, using the same three-pass agent pattern I designed for [Flux](https://github.com/tinggeidel) — implementer, auditor, polisher. Built because writing 30 cover letters by hand drifts toward generic; a well-tuned agent keeps every letter at the same bar.

## How it works

```
$ python apply.py postings/anthropic-fde.txt

Reading job posting…
Drafting cover letter to Anthropic (Forward Deployed Engineer)…
Critique pass — checking for AI-tells, generic phrases, unsupported claims…
Polishing…

✓ letters/2026-05-27-anthropic-forward-deployed-engineer.md
```

Three passes against the Claude API:

1. **Implementer** drafts a cover letter using my resume content, voice principles, and the JD.
2. **Auditor** critiques the draft against the voice principles — flags AI-tells, generic phrases, missing JD signals, claims unsupported by the resume.
3. **Polisher** produces the final, addressing every critique point while keeping voice intact.

The agent's "brain" is three editable markdown files in `knowledge/`:

- `resume.md` — my actual resume content so the agent can pull specifics for tailoring
- `voice.md` — the writing principles (concrete > abstract, no rule-of-three, no "Don't just X; Y", named tools not buzzwords)
- `story.md` — the career arc that fuels the personal hook

Refining the letters is mostly a matter of refining these files, not the code.

## Setup

```bash
# 1. Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your Anthropic API key
cp .env.example .env
# Open .env in any text editor and paste in your key from
# https://console.anthropic.com (never commit .env to git).
```

## Usage

```bash
# Save a job posting as a text file in postings/
# Then run:
python apply.py postings/my-posting.txt

# Or pipe text directly:
cat job-description.txt | python apply.py -
```

Output lands in `letters/` with a date- and company-prefixed filename.

## Architecture notes

- Default model: `claude-sonnet-4-6` for all three passes (override with `MODEL` env var)
- Cost per letter: ~$0.05–0.15 depending on JD length
- `postings/` and `letters/` are gitignored (private application data stays local)
- The knowledge files are tracked — they're the interesting part of this repo

## License

MIT
