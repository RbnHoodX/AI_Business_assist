# Business Knowledge Assistant

Answers business questions from two sources — a SQLite database and PDF
documents. A router decides which source each question needs (often both),
results are merged into one answer, and every statement is cited back to a
database row or a PDF page.

Example:

> What contracts expire in the next 90 days and what penalties are defined in
> those contracts?

The expiry filter runs as SQL; the penalty clauses come from the PDFs linked to
the matching rows. English and Hebrew both work.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # add your ANTHROPIC_API_KEY

python -m data.build_database   # sample data, all fictional
python -m data.generate_pdfs
```

## Run

```bash
streamlit run app.py                        # web UI
python demo.py                              # example questions, full trace (CLI)
python -m assistant.cli "your question"     # single question (CLI)
python self_test.py                         # tests (--offline skips API calls)
```

The web UI and CLI show the same thing. The web version is in `app.py`; it reads
`ANTHROPIC_API_KEY` from `.env` locally, or from Streamlit secrets when deployed
(`.streamlit/secrets.toml.example` lists the keys). The sample data is built on
first run if it isn't there yet.

The CLI prints every step: the routing decision, the generated SQL and rows,
the retrieved PDF pages, the answer with `[DB:...]` / `[DOC:...]` citations,
and a final check that each citation matches something actually retrieved.
`demo_output.txt` has sample runs.
