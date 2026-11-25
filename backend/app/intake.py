"""Conservative extraction: source quotes retained and unread marks left null."""
import asyncio
import csv
import os
import re
import subprocess
import zipfile
from io import BytesIO, StringIO
from pathlib import Path

from app.domain import Evidence, Metadata, Question
from app.paper_figures import CONTINUED_FIGURE_REFERENCE, PDF_RENDER_LOCK, bare_figure_caption

MAX_BYTES = 15 * 1024 * 1024
ALLOWED = {'.pdf', '.docx', '.txt', '.png', '.jpg', '.jpeg'}


def check_file(content, suffix):
    if not content or len(content) > MAX_BYTES:
        raise ValueError('File must be nonempty and at most 15 MB.')
    if suffix not in ALLOWED:
        raise ValueError('Use PDF, DOCX, UTF-8 TXT, PNG, or JPEG.')
    signatures = {'.pdf': b'%PDF-', '.docx': b'PK', '.png': b'\x89PNG\r\n\x1a\n', '.jpg': b'\xff\xd8', '.jpeg': b'\xff\xd8'}
    if suffix in signatures and not content.startswith(signatures[suffix]):
        raise ValueError('File content does not match its extension.')


def ocr_image(image):
    if os.environ.get('SCRUTINY_OCR') == 'tesseract':
        return tesseract_image(image)
    try:
        import winocr
        async def recognize():
            # WinRT returns an awaitable IAsyncOperation, not a coroutine accepted
            # directly by asyncio.run(). Await it inside a real coroutine.
            return await winocr.recognize_pil(image)
        result = asyncio.run(recognize())
        lines=[]
        for line in result.lines:
            words=[{'text':word.text,'x':word.bounding_rect.x,'y':word.bounding_rect.y,
                    'width':word.bounding_rect.width,'height':word.bounding_rect.height} for word in line.words]
            lines.append({'text':line.text,'words':words})
        return {'text':'\n'.join(line.text for line in result.lines),'ocr_lines':lines}
    except ImportError:
        raise ValueError('Image OCR unavailable. Supply searchable PDF/TXT or install optional Windows OCR.')


def tesseract_image(image, *, table=False):
    buffer = BytesIO()
    image.convert('RGB').save(buffer,format='PNG')
    command = ['tesseract','stdin','stdout','-l','eng']
    if table:
        command.extend(['--psm','6','-c','load_system_dawg=0','-c','load_freq_dawg=0'])
    command.append('tsv')
    try:
        result = subprocess.run(command,input=buffer.getvalue(),
                                capture_output=True,check=True,timeout=22)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Server OCR could not read this image. Try a clear scan or searchable PDF.') from exc
    lines = {}
    for row in csv.DictReader(StringIO(result.stdout.decode('utf-8')),delimiter='\t'):
        text = (row.get('text') or '').strip()
        if row['level'] != '5' or not text:
            continue
        key = tuple(row[field] for field in ('page_num','block_num','par_num','line_num'))
        lines.setdefault(key,[]).append({'text':text,'x':int(row['left']),'y':int(row['top']),
                                         'width':int(row['width']),'height':int(row['height'])})
    ordered = [{'text':' '.join(w['text'] for w in words),'words':words} for words in lines.values()]
    return {'text':'\n'.join(line['text'] for line in ordered),'ocr_lines':ordered}


def image_text(image):
    return ocr_image(image)['text']


def read_document(path: Path):
    suffix = path.suffix.lower()
    warnings, pages = [], []
    if suffix == '.txt':
        pages = [{'page': 1, 'text': path.read_text(encoding='utf-8-sig'), 'method': 'text'}]
    elif suffix == '.pdf':
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            if not 1 <= len(pdf.pages) <= 100:
                raise ValueError('PDF must have between 1 and 100 pages.')
            for index, page in enumerate(pdf.pages):
                text, method, ocr = page.extract_text() or '', 'pdf_text', {}
                if not text.strip():
                    try:
                        import pypdfium2 as pdfium
                        with PDF_RENDER_LOCK, pdfium.PdfDocument(str(path)) as raster:
                            source_page = raster[index]
                            bitmap = source_page.render(scale=2)
                            try:
                                scanned = bitmap.to_pil().copy()
                            finally:
                                bitmap.close()
                                source_page.close()
                        with scanned:
                            ocr = ocr_image(scanned)
                        text = ocr['text']
                        method = 'ocr'
                    except Exception as exc:
                        warnings.append(f'Page {index+1}: OCR failed ({type(exc).__name__}); manual transcription required.')
                pages.append({'page': index+1, 'text': text, 'method': method, **ocr})
                if page.images:
                    warnings.append(f'Page {index+1} has image regions; inspect figures and scanned text.')
    elif suffix == '.docx':
        from docx import Document
        from docx.oxml.ns import qn
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > 2000 or sum(e.file_size for e in archive.infolist()) > 50*1024*1024:
                raise ValueError('DOCX expanded content too large.')
        doc, lines = Document(path), []
        figure_questions = set()
        for block in doc.element.body:
            if block.tag == qn('w:p'):
                lines.append(Paragraph(block, doc).text)
            elif block.tag == qn('w:tbl'):
                for row in Table(block, doc).rows:
                    cells = row.cells
                    # A paragraph break belongs to its cell, not to a new table row.
                    values = [' '.join(cell.text.split()) for cell in cells]
                    lines.append(' | '.join(values))
                    if len(cells) == 3 and re.fullmatch(r'[1-8](?:\s*[ab])?',values[0],re.I):
                        if next(cells[1]._tc.iter(qn('w:drawing')), None) is not None:
                            figure_questions.add(values[0].lower().replace(' ',''))
        pages = [{'page':1, 'text':'\n'.join(lines), 'method':'docx_flow', 'figure_questions':sorted(figure_questions)}]
        warnings.append('DOCX page positions need visual confirmation.')
    else:
        from PIL import Image
        with Image.open(path) as image:
            if image.width*image.height > 30_000_000:
                raise ValueError('Image exceeds 30 megapixels.')
            pages = [{'page': 1, 'method': 'ocr', **ocr_image(image)}]
    if not any(page['text'].strip() for page in pages):
        raise ValueError('No readable text was extracted. OCR failed; this document was not accepted.')
    return pages, warnings


def table_annotations(pages):
    """Read labels by question-number column, preserving blank cells."""
    annotations = {}
    warnings = []
    kinds = {'course outcome':'co', 'program outcome':'po', 'programme outcome':'po',
             'blooms level':'level', 'bloom level':'level', 'bloom taxonomy level':'level',
             'bloom s level':'level', 'blooms taxonomy level':'level'}
    for page in pages:
        numbers = []
        for line in page['text'].splitlines():
            cells = [cell.strip() for cell in line.split('|')]
            heading = ' '.join(re.findall(r'\w+', cells[0].lower()))
            if heading in ('question no', 'question number', 'q no'):
                numbers = [cell.lower().replace(' ', '') for cell in cells[1:]]
                numbers = [qid if re.fullmatch(r'[1-8][ab]?', qid) else '' for qid in numbers]
                continue
            if heading in ('subpart', 'sub question', 'part') and len(cells)-1 == len(numbers):
                numbers = [qid+cell.lower().strip('(). ') if len(qid)==1 and cell.lower().strip('(). ') in ('a','b') else qid
                           for qid,cell in zip(numbers,cells[1:])]
                continue
            kind = kinds.get(heading)
            if not kind or not numbers or len(cells)==1:
                continue
            if len(cells)-1 != len(numbers):
                warnings.append(f'Page {page["page"]}: the {cells[0]} row does not line up with the question numbers.')
                continue
            for qid, cell in zip(numbers, cells[1:]):
                if not qid or not cell:
                    continue
                if kind == 'level':
                    found = re.fullmatch(r'(?:L|BL|BTL|Level)\s*[-:]?\s*([1-6])', cell, re.I)
                    value = int(found[1]) if found else None
                else:
                    prefix = kind.upper()
                    value = list(dict.fromkeys(prefix+n for n in re.findall(r'\b'+prefix+r'\s*([1-9]\d*)\b', cell, re.I)))
                if value:
                    entries = annotations.setdefault(qid, {})
                    entries.setdefault(kind, []).append(value)
    return annotations, warnings


def parse_outcome_statements(pages):
    outcomes = {}
    for page in pages:
        for line in page['text'].splitlines():
            match = re.match(r'^\s*(CO[1-9]\d*)\s*[:|]\s*(.+)', line, re.I)
            if match and re.search(r'[A-Za-z]{3,}', match[2]) and '|' not in match[2]:
                outcomes[match[1].upper()] = match[2].strip()
    return outcomes


def parse_proposals(pages, document_id):
    annotations, warnings = table_annotations(pages)
    questions = []
    current, main = None, None

    def flush():
        nonlocal current
        if current is None:
            return
        body = ' '.join(current['lines']).strip()
        co = re.findall(r'\bCO\s*([1-9]\d*)\b', body, re.I)
        po = re.findall(r'\bPO\s*(1[0-2]|[1-9])\b', body, re.I)
        levels = re.findall(r'\bL\s*([1-6])\b', body, re.I)
        body = re.sub(r'\b(?:CO\s*[1-9]\d*|PO\s*(?:1[0-2]|[1-9])|L\s*[1-6])\b', '', body, flags=re.I)
        marks = current.get('marks')
        match = re.search(r'(?:\[|\()?\s*(\d{1,2}(?:\.\d+)?)\s*(?:marks?)?\s*(?:\]|\))?\s*$', body, re.I)
        if marks is None and not current.get('table') and match and 0 < float(match.group(1)) <= 10:
            marks, body = match.group(1), body[:match.start()].strip(' |')
        qid = current['q_no']
        values = {'co':list(dict.fromkeys('CO'+v for v in co)), 'po':list(dict.fromkeys('PO'+v for v in po)),
                  'level':int(levels[-1]) if len(set(levels)) == 1 else None}
        for kind, printed in annotations.get(qid, {}).items():
            if len(printed) != 1 or (values[kind] and values[kind] != printed[0]):
                values[kind] = None if kind == 'level' else []
                warnings.append(f'Q{qid}: conflicting or repeated {kind.upper()} entries. Check the printed table.')
            else:
                values[kind] = printed[0]
        questions.append(Question(q_no=qid, text=body or '[Unread question: source review required]', marks=marks,
            co=values['co'], po=values['po'], stated_level=values['level'], evidence=current['evidence']))
        current = None

    combined = '\n'.join(p['text'] for p in pages)
    for page in pages:
        for raw in page['text'].splitlines():
            line = raw.strip()
            if bare_figure_caption(line) and (current is None or
                    not CONTINUED_FIGURE_REFERENCE.search(current['lines'][-1].rstrip())):
                flush()
                continue
            cells = [cell.strip() for cell in raw.split('|')]
            if len(cells) == 3 and re.fullmatch(r'[1-8](?:\s*[ab])?|[ab][.)]?',cells[0],re.I) and cells[1]:
                flush()
                qid = cells[0].lower().replace(' ', '').rstrip('.)')
                if qid in ('a','b') and main:
                    qid = main + qid
                if not re.fullmatch(r'[1-8][ab]?',qid):
                    continue
                main = qid[0]
                mark = re.fullmatch(r'(\d{1,2}(?:\.\d+)?)\s*(?:marks?)?', cells[2], re.I)
                value = mark[1] if mark and 0 < float(mark[1]) <= 10 else None
                current = {'q_no':qid, 'lines':[cells[1]], 'marks':value, 'table':True,
                           'evidence':[Evidence(document_id=document_id,page=page['page'],quote=line)]}
                continue
            if current and current.get('table') and len(cells)>1:
                flush()
                continue
            if re.fullmatch(r'\(?\s*OR\s*\)?', line, re.I):
                flush()
                continue
            if re.match(r'^(?:Answer\s+five|Question\s+No|Course\s+Outcome|Program\w*\s+Outcome|Bloom|Subpart)', line, re.I):
                continue
            numbered = re.match(r'^(?:Q\s*)?([1-8])(?:\s*[.)]?\s+|\s*(?=[ab][.)]))(?:\(?([ab])\)?[.)]?\s+)?(.+)$', line, re.I)
            part = re.match(r'^\(?([ab])\)?[.)]\s+(.+)$', line, re.I)
            if numbered and re.search(r'[A-Za-z]', numbered.group(3)):
                flush()
                main = numbered.group(1)
                current = {'q_no': main+(numbered.group(2) or '').lower(), 'lines': [numbered.group(3)], 'evidence': [Evidence(document_id=document_id,page=page['page'],quote=numbered.group(3))]}
            elif part and main:
                flush()
                current = {'q_no': main+part.group(1).lower(), 'lines': [part.group(2)], 'evidence': [Evidence(document_id=document_id,page=page['page'],quote=part.group(2))]}
            elif current and line:
                current['lines'].append(line)
                current['evidence'].append(Evidence(document_id=document_id,page=page['page'],quote=line))
    flush()
    fields = {}
    patterns = {
        'course_code': r'(?:Course|Subject)\s*Code\s*[:\-]?\s*([A-Z0-9]+)',
        'course_name': r'(?:Course(?:\s*(?:Name|Title))?|Subject)\s*[:\-]\s*([^\n]+?)(?=\s{2,}(?:Maximum|Max)\s+Marks|\n|$)',
        'semester': r'Semester\s*[:\-]\s*([IVX\d]+)',
        'date': r'Date\s*[:\-]\s*(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4})',
        'duration': r'Duration\s*[:\-]\s*([^\n]+)',
        'max_marks': r'(?:Maximum|Max)\s*marks\s*[:\-]\s*(\d+)',
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, combined[:5000], re.I)
        if match:
            fields[key] = match.group(1).strip()
    if questions and any(q.stated_level is None for q in questions):
        warnings.append('Some printed Bloom’s levels could not be matched reliably to a question. Check the original labels.')
    for qid in sorted({qid for page in pages for qid in page.get('figure_questions', [])}):
        warnings.append(f'Q{qid}: embedded figure found in the original Word file.')
    return Metadata(**fields), questions, warnings
