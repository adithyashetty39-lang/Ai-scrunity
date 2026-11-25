"""Locate visual evidence in the original paper without guessing missing labels."""
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from threading import Lock
from zipfile import BadZipFile, ZipFile

from PIL import Image, ImageOps


FIGURE_LABEL = re.compile(r'\b(?:figure|fig)\s*\.?\s*(?:no\s*\.?\s*)?[:#-]?\s*(\d+[a-z]?)\b', re.I)
CONTINUED_FIGURE_REFERENCE = re.compile(r'(?:\b(?:in|using|use|see|refer to|from)\s*|:)\Z', re.I)
SUPPLIED_FIGURE = re.compile(
    r'\b(?:refer to|see|shown in|given in|provided in|as in)\s+(?:the\s+)?'
    r'(?:figure|fig\.?|diagram|chart|(?:game )?tree|graph)\b'
    r'|\b(?:use|using)\s+(?:the|this|following|given|supplied|provided|accompanying)\s+'
    r'(?:(?:following|given|supplied|provided|accompanying)\s+)?'
    r'(?:figure|diagram|chart|(?:game )?tree|graph)\b(?!\s+(?:traversal|search|algorithm|theory))'
    r'|\b(?:figure|diagram|chart|tree|graph)\s+(?:above|below|provided|supplied|shown)\b'
    r'|\b(?:shown|illustrated)\s+(?:below|above)\b'
    r'|\bblock\s+world\s+(?:problem\s+)?(?:given|provided)\s+(?:below|above)\b'
    r'|'+FIGURE_LABEL.pattern, re.I,
)
MAX_EDGE = 1800
PDF_RENDER_LOCK = Lock()


@dataclass(frozen=True)
class FigureSource:
    document_id: str
    path: Path
    kind: str
    index: int
    caption_number: str | None = None

    def public(self):
        label = f'Embedded figure {self.index}' if self.kind == 'embedded' else f'Paper page {self.index}'
        if self.caption_number:
            label = (f'Figure {self.caption_number}' if self.kind == 'embedded'
                     else f'Figure {self.caption_number} on page {self.index}')
        return {'document_id': self.document_id, 'kind': self.kind, 'index': self.index, 'label': label}

    def jpeg(self):
        if self.kind == 'embedded':
            try:
                entry = next((figure.data for figure in docx_images(self.path) if figure.index == self.index), None)
            except BadZipFile as exc:
                raise ValueError('The original Word file could not be opened.') from exc
            if entry is None:
                raise ValueError('The embedded figure could not be found.')
            return open_image(BytesIO(entry))
        if self.path.suffix == '.pdf':
            import pypdfium2 as pdfium
            with PDF_RENDER_LOCK, pdfium.PdfDocument(str(self.path)) as pdf:
                if not 1 <= self.index <= len(pdf):
                    raise ValueError('The cited paper page does not exist.')
                page = pdf[self.index - 1]
                try:
                    bitmap = page.render(scale=min(2.5, MAX_EDGE / max(page.get_size())))
                    try:
                        with bitmap.to_pil() as image:
                            return to_jpeg(image)
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        if self.path.suffix in ('.png', '.jpg', '.jpeg') and self.index == 1:
            return open_image(self.path)
        raise ValueError('This source does not have a viewable page.')


def open_image(source):
    try:
        with Image.open(source) as image:
            return to_jpeg(image)
    except Image.DecompressionBombError as exc:
        raise ValueError('The figure exceeds the safe image size.') from exc


def to_jpeg(image):
    if image.width * image.height > 30_000_000:
        raise ValueError('The figure exceeds 30 megapixels.')
    rgba = ImageOps.exif_transpose(image).convert('RGBA')
    rgba.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    background = Image.new('RGB', rgba.size, 'white')
    background.paste(rgba, mask=rgba.getchannel('A'))
    output = BytesIO()
    background.save(output, 'JPEG', quality=91)
    return output.getvalue()


@dataclass(frozen=True)
class EmbeddedFigure:
    index: int
    data: bytes
    question_number: str | None = None
    caption_number: str | None = None


def caption_numbers(text):
    """Read caption labels in order, including several captions on one line."""
    for line in text.splitlines():
        for column in re.split(r'\s{2,}|\|', line):
            remaining = column.strip().lstrip('([')
            while match := FIGURE_LABEL.match(remaining):
                yield match[1].lower()
                remaining = remaining[match.end():].lstrip(' ()[]:.,;/&-')


def bare_figure_caption(text):
    remaining, count = FIGURE_LABEL.subn('',text)
    return count > 0 and not remaining.strip(' \t\n()[]:.,;/&|-')


def question_figure_text(question):
    """Exclude standalone captions appended to questions by older extractors."""
    text = question.text
    for evidence in reversed(question.evidence):
        quote = evidence.quote.strip()
        if not bare_figure_caption(quote) or not text.endswith(quote):
            break
        before = text[:-len(quote)].rstrip()
        if not before or CONTINUED_FIGURE_REFERENCE.search(before):
            break
        text = before
    return text


def question_row_number(row):
    cells = row.cells
    if len(cells) == 3:
        number = re.fullmatch(r'[1-8](?:\s*[ab])?', cells[0].text.strip(), re.I)
        if number:
            return re.sub(r'\s+', '', number[0]).lower()
    return None


def image_parts(document, element):
    from docx.oxml.ns import qn

    for blip in element.iter(qn('a:blip')):
        relationship = blip.get(qn('r:embed'))
        part = document.part.related_parts.get(relationship)
        if part and part.content_type in ('image/png', 'image/jpeg', 'image/gif', 'image/bmp', 'image/tiff'):
            yield relationship, part.blob


def captioned_docx_images(document):
    """Pair image runs and following caption runs in document order."""
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def paragraphs():
        for block in document.element.body:
            if block.tag == qn('w:p'):
                yield Paragraph(block,document)
            elif block.tag == qn('w:tbl'):
                for row in Table(block,document).rows:
                    if question_row_number(row):
                        yield None
                        continue
                    seen = set()
                    for cell in row.cells:
                        if cell._tc not in seen:
                            seen.add(cell._tc)
                            yield from cell.paragraphs

    pictures, numbers = [], []
    for paragraph in paragraphs():
        if paragraph is None:
            pictures, numbers = [], []
            continue
        captions = list(caption_numbers(paragraph.text))
        if paragraph.text.strip() and not captions:
            pictures, numbers = [], []
            continue
        images = [data for _, data in image_parts(document,paragraph._p)]
        if images:
            if numbers:
                pictures, numbers = [], []
            pictures.extend(images)
        if captions and pictures:
            numbers.extend(captions)
            if len(numbers) == len(pictures):
                yield from zip(numbers,pictures)
                pictures, numbers = [], []
            elif len(numbers) > len(pictures):
                pictures, numbers = [], []


def docx_images(path):
    """Keep the existing inline indexes, then add caption-linked figures."""
    from docx import Document

    with ZipFile(path) as archive:
        names = archive.infolist()
        if len(names) > 2000 or sum(entry.file_size for entry in names) > 50 * 1024 * 1024:
            raise ValueError('DOCX expanded content exceeds the reading limit.')
    document = Document(path)
    index = 0
    for table in document.tables:
        for row in table.rows:
            number = question_row_number(row)
            if not number:
                continue
            seen = set()
            for relationship,data in image_parts(document,row.cells[1]._tc):
                if relationship in seen:
                    continue
                seen.add(relationship)
                index += 1
                yield EmbeddedFigure(index,data,question_number=number)
    for number,data in captioned_docx_images(document):
        index += 1
        yield EmbeddedFigure(index,data,caption_number=number)


def caption_pages(path, pages, wanted):
    matches = {number:set() for number in wanted}

    def collect(page, text, numbers):
        for number in numbers.intersection(caption_numbers(text)):
            matches[number].add(page)

    for page in pages:
        collect(page['page'],page['text'],wanted)
    missing = {number for number in wanted if not matches[number]}
    if missing and path.suffix == '.pdf':
        import pdfplumber
        from pdfminer.pdfparser import PDFSyntaxError

        try:
            with pdfplumber.open(path) as pdf:
                for page in pdf.pages:
                    collect(page.page_number,page.extract_text(layout=True) or '',missing)
        except (OSError, ValueError, PDFSyntaxError):
            pass
    return matches


def visual_sources(repo, owner, submission):
    """Return candidates only for questions with an embedded image or a supplied-figure reference."""
    result = {}
    for paper in submission.sets:
        question_texts = {q.q_no:question_figure_text(q) for q in paper.questions}
        figure_questions = {number for number,text in question_texts.items() if SUPPLIED_FIGURE.search(text)}
        references = {number:[] for number in figure_questions}
        labels = {number:list(dict.fromkeys(label.lower() for label in FIGURE_LABEL.findall(question_texts[number])))
                  for number in figure_questions}
        for warning in paper.extraction_warnings:
            embedded = re.match(r'^Q([1-8][ab]?):\s.*embedded figure',warning,re.I)
            if embedded:
                references.setdefault(embedded[1].lower(),[])
        for document_id in paper.document_ids:
            try:
                document = repo.document(owner, document_id)
            except KeyError:
                continue
            suffix = document['suffix']
            path = repo.root / 'documents' / (document_id + suffix)
            if suffix == '.docx':
                try:
                    by_caption = {}
                    for figure in docx_images(path):
                        if figure.question_number:
                            references.setdefault(figure.question_number, []).append(
                                FigureSource(document_id,path,'embedded',figure.index))
                        if figure.caption_number:
                            by_caption.setdefault(figure.caption_number,[]).append(figure)
                    for q_no, numbers in labels.items():
                        for number in numbers:
                            matching = by_caption.get(number,[])
                            if len(matching) == 1:
                                references[q_no].append(FigureSource(document_id,path,'embedded',matching[0].index,number))
                except (OSError, ValueError, BadZipFile):
                    continue
                continue
            if suffix not in ('.pdf', '.png', '.jpg', '.jpeg'):
                continue
            pages = document['pages']
            matched_pages = caption_pages(path,pages,{number for numbers in labels.values() for number in numbers})
            for question in paper.questions:
                if question.q_no not in figure_questions:
                    continue
                numbers = labels[question.q_no]
                exact = [(number,next(iter(matched_pages[number]))) for number in numbers if len(matched_pages[number]) == 1]
                if exact:
                    references[question.q_no].extend(FigureSource(document_id,path,'page',page,number)
                                                     for number,page in exact[:2])
                    continue
                possible = set().union(*(matched_pages[number] for number in numbers))
                evidence_pages = list(dict.fromkeys(ev.page for ev in question.evidence if ev.document_id == document_id))
                if evidence_pages:
                    source_pages = [page for page in evidence_pages if not possible or page in possible]
                else:
                    source_pages = [pages[0]['page']] if len(pages) == 1 and len(paper.document_ids) == 1 else []
                references[question.q_no].extend(FigureSource(document_id, path, 'page', number)
                                                 for number in source_pages[:2])
        for q in paper.questions:
            if q.q_no in references:
                result[f'{paper.label}/{q.q_no}'] = references[q.q_no]
    return result
