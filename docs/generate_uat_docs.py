#!/usr/bin/env python3
"""Generate Word (.docx) and PDF versions of the UAT test document."""

import re
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn


def parse_markdown(md_path):
    """Parse the markdown UAT document into structured data."""
    with open(md_path, "r") as f:
        content = f.read()
    return content


def add_table_from_md(doc, lines):
    """Parse markdown table lines and add a formatted table to the document."""
    # Filter out separator lines (|------|...)
    data_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not re.match(r"^\|[-\s|:]+\|$", stripped):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            data_lines.append(cells)

    if len(data_lines) < 2:
        return

    headers = data_lines[0]
    rows = data_lines[1:]

    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # Header row
    hdr_row = table.rows[0]
    for i, header in enumerate(headers):
        cell = hdr_row.cells[i]
        cell.text = header
        for paragraph in cell.paragraphs:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(9)
        # Shade header
        shading = cell._element.get_or_add_tcPr()
        shade_elem = shading.makeelement(
            qn("w:shd"),
            {
                qn("w:val"): "clear",
                qn("w:color"): "auto",
                qn("w:fill"): "2B579A",
            },
        )
        shading.append(shade_elem)
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.font.color.rgb = RGBColor(255, 255, 255)

    # Data rows
    for r_idx, row_data in enumerate(rows):
        row = table.rows[1 + r_idx]
        for c_idx, cell_text in enumerate(row_data):
            if c_idx < len(headers):
                cell = row.cells[c_idx]
                cell.text = cell_text
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(9)

    # Set column widths
    if len(headers) == 4:
        widths = [Cm(1.2), Cm(7), Cm(6), Cm(2)]
        for row in table.rows:
            for idx, width in enumerate(widths):
                if idx < len(row.cells):
                    row.cells[idx].width = width

    doc.add_paragraph("")  # spacing


def generate_docx(md_path, docx_path):
    """Generate a Word document from the markdown UAT file."""
    with open(md_path, "r") as f:
        lines = f.readlines()

    doc = Document()

    # Set default font
    style = doc.styles["Normal"]
    font = style.font
    font.name = "Calibri"
    font.size = Pt(10)

    # Page margins
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2)
        section.right_margin = Cm(2)

    i = 0
    table_lines = []
    in_table = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Title (# heading)
        if stripped.startswith("# ") and not stripped.startswith("## "):
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            title = stripped[2:]
            p = doc.add_heading(title, level=0)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            i += 1
            continue

        # Metadata lines (bold key: value)
        if stripped.startswith("**") and "**:" in stripped:
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            # Parse **Key**: Value
            match = re.match(r"\*\*(.+?)\*\*:\s*(.*)", stripped)
            if match:
                p = doc.add_paragraph()
                p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = p.add_run(f"{match.group(1)}: ")
                run.bold = True
                run.font.size = Pt(10)
                run = p.add_run(match.group(2))
                run.font.size = Pt(10)
            i += 1
            continue

        # Horizontal rule
        if stripped == "---":
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            i += 1
            continue

        # H2 heading (## )
        if stripped.startswith("## "):
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            heading_text = stripped[3:]
            doc.add_heading(heading_text, level=1)
            i += 1
            continue

        # H3 heading (### )
        if stripped.startswith("### "):
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            heading_text = stripped[4:]
            doc.add_heading(heading_text, level=2)
            i += 1
            continue

        # Table lines
        if stripped.startswith("|"):
            in_table = True
            table_lines.append(stripped)
            i += 1
            continue

        # End of table
        if in_table and not stripped.startswith("|"):
            add_table_from_md(doc, table_lines)
            table_lines = []
            in_table = False

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            text = re.sub(r"^\d+\.\s", "", stripped)
            # Handle bold within list
            p = doc.add_paragraph(style="List Number")
            parts = re.split(r"(\*\*.+?\*\*)", text)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
            i += 1
            continue

        # Regular paragraph
        if stripped and not stripped.startswith("|"):
            if in_table:
                add_table_from_md(doc, table_lines)
                table_lines = []
                in_table = False
            p = doc.add_paragraph()
            # Handle inline bold
            parts = re.split(r"(\*\*.+?\*\*)", stripped)
            for part in parts:
                if part.startswith("**") and part.endswith("**"):
                    run = p.add_run(part[2:-2])
                    run.bold = True
                else:
                    p.add_run(part)
            i += 1
            continue

        i += 1

    # Flush remaining table
    if in_table:
        add_table_from_md(doc, table_lines)

    doc.save(docx_path)
    print(f"Generated: {docx_path}")


def generate_pdf(docx_path, pdf_path):
    """Convert docx to PDF using LibreOffice."""
    output_dir = str(Path(pdf_path).parent)
    try:
        subprocess.run(
            [
                "libreoffice",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )
        # LibreOffice outputs with the same name but .pdf extension
        expected_output = Path(output_dir) / (Path(docx_path).stem + ".pdf")
        if expected_output.exists() and str(expected_output) != str(pdf_path):
            expected_output.rename(pdf_path)
        print(f"Generated: {pdf_path}")
    except subprocess.CalledProcessError as e:
        print(f"PDF generation failed: {e.stderr.decode()}", file=sys.stderr)
    except FileNotFoundError:
        print("LibreOffice not found. Install with: sudo apt install libreoffice", file=sys.stderr)


if __name__ == "__main__":
    docs_dir = Path(__file__).parent
    md_path = docs_dir / "UAT_TEST_DOCUMENT.md"
    docx_path = docs_dir / "UAT_TEST_DOCUMENT.docx"
    pdf_path = docs_dir / "UAT_TEST_DOCUMENT.pdf"

    print("Generating Word document...")
    generate_docx(md_path, docx_path)

    print("Generating PDF...")
    generate_pdf(docx_path, pdf_path)

    print("Done!")
