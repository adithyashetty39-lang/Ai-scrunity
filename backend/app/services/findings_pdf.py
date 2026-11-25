"""Flowing question findings appended to the fixed departmental form."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer


def findings_fonts(roman, bold):
    candidates = (
        (Path('/usr/share/fonts/truetype/dejavu'), 'DejaVuSans.ttf', 'DejaVuSans-Bold.ttf'),
        (Path('C:/Windows/Fonts'), 'arial.ttf', 'arialbd.ttf'),
    )
    for folder, regular, strong in candidates:
        if (folder / regular).is_file() and (folder / strong).is_file():
            for name, file in (('Findings-Regular', regular), ('Findings-Bold', strong)):
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, str(folder / file)))
            return 'Findings-Regular', 'Findings-Bold'
    return roman, bold


def append_findings(canvas, form, roman, bold):
    width, height = canvas._pagesize
    normal, strong = findings_fonts(roman, bold)
    green, ink, muted = map(colors.HexColor, ('#244C3B', '#223229', '#4D6055'))
    question_style = ParagraphStyle('Question', fontName=strong, fontSize=15, leading=19,
                                    textColor=green, spaceBefore=15, spaceAfter=5, keepWithNext=True)
    body = ParagraphStyle('Finding', fontName=normal, fontSize=9.5, leading=13, textColor=ink, spaceAfter=5)
    caption = ParagraphStyle('Caption', parent=body, fontSize=8.5, leading=11, textColor=muted)
    label_style = ParagraphStyle('Check', parent=body, fontName=strong, spaceBefore=3, spaceAfter=2,
                                 keepWithNext=True)
    story = []
    question_blocks = []

    def paragraph(text, style=body, lead=''):
        content = escape(text).replace('\n', '<br/>')
        if lead:
            content = f'<font name="{strong}">{lead}</font>  {content}'
        question_blocks.append(Paragraph(content, style))

    for question in form['question_findings']:
        question_blocks = []
        paragraph(f"Set {question['set_label']} - Question {question['q_no']}", question_style)
        paragraph(f"Printed Bloom’s {question['printed_level']} | AI suggestion {question['suggested_level']} | "
                  f"Faculty-reviewed {question['faculty_level']} | {question['marks']} marks | "
                  f"{question['co']} / {question['po']}", caption)
        decision = question['faculty_bloom_decision']
        if decision:
            paragraph('Faculty decision - '+decision['label'], label_style)
            if decision['note']:
                paragraph(decision['note'], lead='Faculty note')
        paragraph(question['text'])
        for item in question['checks']:
            paragraph(f"{item['label']} - {item['status']}", label_style)
            paragraph(item['reason'], lead='Why')
            paragraph(item['suggestion'], lead='Suggestion')
        for source in question['figure_sources']:
            paragraph(source['label'] + ' in the original question paper.', caption, lead='Visual evidence')
        for citation in question['citations']:
            paragraph(f"Evidence - {citation['source']}", label_style)
            paragraph(citation['quote'], caption)
        if question['rewrite']:
            paragraph('Suggested wording', label_style)
            paragraph(question['rewrite'])
        if question['verification_feedback']:
            paragraph('AI verification - ' + question['verification_feedback'], caption)
        story.append(KeepTogether([*question_blocks, Spacer(1, 8)]))

    def header_footer(page, _document):
        page.setFillColor(green)
        page.setFont(strong, 15)
        page.drawString(42, height - 38, 'Question-by-question findings')
        page.setStrokeColor(colors.HexColor('#CFDCD2'))
        page.line(42, height - 48, width - 42, height - 48)
        page.setFont(normal, 8)
        page.setFillColor(muted)
        page.drawString(42, 23, 'DRAFT - NOT APPROVED | ' + form['draft_id'])
        page.drawRightString(width - 42, 23, str(page.getPageNumber()))

    document = SimpleDocTemplate(None, pagesize=(width, height), leftMargin=36, rightMargin=36,
                                 topMargin=54, bottomMargin=39, title='Question Paper Scrutiny Format',
                                 author=form.get('institution', ''), subject=form.get('course_code', ''))
    document.build(story, onFirstPage=header_footer, onLaterPages=header_footer,
                   canvasmaker=lambda *_args, **_kwargs: canvas)
