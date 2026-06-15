"""Generate sanitized sample contract & project PDFs.

Each logical section (Penalties, Service Suspension, Risks, ...) is placed on its
own page so that page-level citations map cleanly onto a meaning. One contract
and one project are authored in Hebrew to exercise multilingual retrieval.

Run:  python -m data.generate_pdfs
"""
from __future__ import annotations

import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from assistant.config import PDF_DIR  # noqa: E402

# Register a Hebrew-capable font so RTL contract text actually renders (the
# default Helvetica has no Hebrew glyphs and would extract as garbage).
_HEBREW_FONT = "Helvetica"
for candidate in (
    # DejaVu Sans covers Hebrew AND Latin/digits/punctuation, so mixed-script
    # contract text (amounts, IDs) extracts cleanly.
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/noto/NotoSansHebrew-Regular.ttf",
):
    if Path(candidate).exists():
        pdfmetrics.registerFont(TTFont("Hebrew", candidate))
        _HEBREW_FONT = "Hebrew"
        break

styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Heading1"], fontSize=15, spaceAfter=12)
BODY = ParagraphStyle("BODY", parent=styles["BodyText"], fontSize=11, leading=16)


def _is_rtl(text: str) -> bool:
    return any("֐" <= ch <= "׿" for ch in text)


HE = ParagraphStyle("HE", parent=BODY, fontName=_HEBREW_FONT, alignment=2)   # right
HE_H = ParagraphStyle("HE_H", parent=H, fontName=_HEBREW_FONT, alignment=2)


def _doc(filename: str, title: str, sections: list[tuple[str, str]]) -> None:
    """sections = list of (heading, body); each becomes its own page."""
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    path = PDF_DIR / filename
    doc = SimpleDocTemplate(
        str(path), pagesize=LETTER,
        topMargin=0.9 * inch, bottomMargin=0.9 * inch,
        title=title,
    )
    flow = []
    for i, (heading, body) in enumerate(sections):
        if i > 0:
            flow.append(PageBreak())
        h_style = HE_H if _is_rtl(heading) else H
        flow.append(Paragraph(heading, h_style))
        flow.append(Spacer(1, 6))
        for para in body.strip().split("\n\n"):
            para = para.strip()
            b_style = HE if _is_rtl(para) else BODY
            flow.append(Paragraph(para, b_style))
            flow.append(Spacer(1, 6))
    doc.build(flow)
    print(f"  wrote {path.name} ({len(sections)} pages)")


# --- English contract template ----------------------------------------------
def contract_sections(name: str, contract_id: str, penalty_per_day: str,
                       penalty_cap: str, suspend_days: int) -> list[tuple[str, str]]:
    return [
        (f"{name} — Master Agreement ({contract_id})",
         f"This Agreement governs the provision of services between the Provider "
         f"and {name}. Capitalized terms have the meanings given in the Definitions "
         f"section. This document is sanitized sample data for demonstration."),
        ("1. Term and Renewal",
         "The initial Term runs from the Effective Date through the Expiry Date set "
         "out in the order form. Unless either party gives written notice of "
         "non-renewal at least sixty (60) days before expiry, the Term renews for "
         "successive twelve (12) month periods."),
        ("2. Payment Terms",
         "Fees are invoiced annually in advance and are due within thirty (30) days "
         "of the invoice date. Amounts not paid when due accrue interest at 1.5% per "
         "month."),
        ("3. Penalties",
         f"If the Provider fails to deliver a committed milestone by its due date, a "
         f"late-delivery penalty of {penalty_per_day} per business day shall apply, "
         f"up to an aggregate cap of {penalty_cap} per milestone. Penalties are the "
         f"Customer's sole financial remedy for delay and are credited against future "
         f"invoices."),
        ("4. Service Suspension",
         f"The Provider may suspend the Services, in whole or in part, if undisputed "
         f"fees remain overdue for more than {suspend_days} days after written notice. "
         f"Suspension does not relieve the Customer of payment obligations, and the "
         f"Provider will restore Services within two (2) business days of full "
         f"payment."),
        ("5. Termination",
         "Either party may terminate for material breach not cured within thirty (30) "
         "days of written notice. On termination, the Customer shall pay all fees "
         "accrued up to the effective date of termination."),
    ]


# --- English project template -----------------------------------------------
def project_sections(name: str, risks: list[str]) -> list[tuple[str, str]]:
    risk_body = "\n\n".join(f"R{i+1}. {r}" for i, r in enumerate(risks))
    return [
        (f"{name} — Project Charter",
         f"This charter summarizes scope, schedule, and risk for the {name} "
         f"engagement. Sanitized sample data for demonstration."),
        ("Scope and Objectives",
         "The project delivers the agreed workstreams in phased releases. Acceptance "
         "is based on the criteria recorded in the statement of work."),
        ("Risks",
         "The following risks have been identified and are tracked in the project "
         "risk register:\n\n" + risk_body),
    ]


def build() -> None:
    print("Generating PDFs...")
    _doc("contract_C001.pdf", "Riverstone Master Services Agreement",
         contract_sections("Riverstone Manufacturing", "C001", "$1,000", "$25,000", 15))
    _doc("contract_C002.pdf", "Cobalt SaaS Subscription",
         contract_sections("Cobalt Software", "C002", "$500", "$10,000", 30))
    _doc("contract_C003.pdf", "Greenfield Support & Maintenance",
         contract_sections("Greenfield Logistics", "C003", "$250", "$5,000", 20))
    _doc("contract_C004.pdf", "Halcyon Data Processing Agreement",
         contract_sections("Halcyon Media", "C004", "$750", "$15,000", 10))
    _doc("contract_C005.pdf", "Meridian Software License",
         contract_sections("Meridian Retail", "C005", "$2,000", "$50,000", 25))

    # Hebrew contract (C006). Right-to-left text; sections still one-per-page.
    _doc("contract_C006.pdf", "Galil Cyber Services Agreement",
         [
            ("הסכם שירותי סייבר — טכנולוגיות גליל (C006)",
             "הסכם זה מסדיר את אספקת שירותי הסייבר בין הספק לבין טכנולוגיות גליל. "
             "המסמך הוא נתוני דוגמה מסוננים להדגמה בלבד."),
            ("1. תקופת ההתקשרות",
             "תקופת ההסכם הראשונית הינה עד למועד הפקיעה הנקוב בטופס ההזמנה. "
             "ההסכם יתחדש אוטומטית לתקופות בנות שנים-עשר (12) חודשים אלא אם נמסרה "
             "הודעת אי-חידוש בכתב לפחות שישים (60) יום לפני הפקיעה."),
            ("2. קנסות",
             "במקרה של איחור באספקת אבן דרך, יחול קנס פיגורים בסך 3,000 ש\"ח לכל "
             "יום עסקים, עד לתקרה מצטברת של 60,000 ש\"ח לאבן דרך."),
            ("3. השעיית שירות",
             "הספק רשאי להשעות את השירותים אם תשלום שאינו שנוי במחלוקת נותר בפיגור "
             "למעלה מ-14 ימים לאחר מתן הודעה בכתב. ההשעיה אינה פוטרת את הלקוח "
             "מחובת התשלום."),
         ])

    _doc("project_P001.pdf", "Riverstone Cloud Migration",
         project_sections("Riverstone Cloud Migration", [
             "Data migration cutover may exceed the maintenance window, risking "
             "extended downtime for order-processing systems.",
             "Legacy application has undocumented dependencies that could surface "
             "late in testing and delay go-live.",
             "Key cloud-architect is allocated only part-time, creating a single "
             "point of failure for delivery.",
         ]))
    _doc("project_P002.pdf", "Cobalt ERP Rollout",
         project_sections("Cobalt ERP Rollout", [
             "Scope creep from finance stakeholders threatens the Phase 2 timeline.",
             "Master-data quality in the legacy ERP is poor and may require manual "
             "cleansing before load.",
             "Integration with the third-party tax engine depends on a vendor API "
             "still in beta.",
         ]))
    _doc("project_P003.pdf", "Greenfield Data Lake",
         project_sections("Greenfield Data Lake", [
             "Storage cost growth could exceed budget if retention policies are not "
             "enforced.",
         ]))

    # Hebrew project (P004).
    _doc("project_P004.pdf", "Galil Cyber Defense",
         [
            ("הגנת סייבר — סטארק (P004)",
             "מסמך זה מסכם את היקף הפרויקט והסיכונים. נתוני דוגמה מסוננים בלבד."),
            ("סיכונים",
             "הסיכונים שזוהו ונמצאים במעקב:\n\n"
             "R1. מחסור באנשי אבטחת מידע מנוסים עלול לעכב את פריסת המערכת.\n\n"
             "R2. תלות בספק חיצוני עבור ניטור 24/7 מהווה סיכון לזמינות השירות.\n\n"
             "R3. נתוני לקוח רגישים עלולים להיחשף אם בקרת ההרשאות לא תיושם כראוי."),
         ])

    # Extract the page text into data/corpus.json so the deployed app can load
    # the corpus without pdfplumber or the PDFs at runtime.
    from assistant import doc_retriever
    n = doc_retriever.build_corpus_cache()
    print(f"  wrote corpus.json ({n} page chunks)")
    print("Done.")


if __name__ == "__main__":
    build()
