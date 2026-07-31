"""
Handles exporting the current dashboard view to Excel and PDF.
"""
import io
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet


def to_excel_bytes(df, sheet_name="Cost Report"):
    """Returns an in-memory Excel file (bytes) from a dataframe."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name=sheet_name)
    return output.getvalue()


def to_pdf_bytes(title, summary_text, df, max_rows=25):
    """Returns an in-memory PDF file (bytes) with a title, summary, and a data table."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = [Paragraph(title, styles["Title"]), Spacer(1, 12)]

    if summary_text:
        elements.append(Paragraph("Executive Summary", styles["Heading2"]))
        elements.append(Paragraph(summary_text.replace("\n", "<br/>"), styles["BodyText"]))
        elements.append(Spacer(1, 16))

    elements.append(Paragraph("Cost Detail (top rows)", styles["Heading2"]))
    table_df = df.head(max_rows)
    data = [list(table_df.columns)] + table_df.astype(str).values.tolist()
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f2f2")]),
    ]))
    elements.append(table)

    doc.build(elements)
    return buffer.getvalue()
