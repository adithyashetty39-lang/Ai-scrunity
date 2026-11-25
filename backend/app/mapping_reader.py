"""Read printed CO–PO matrix cells using the positions of OCR words."""
import os
import re
from statistics import median

from app.intake import ocr_image, parse_outcome_statements, parse_proposals, tesseract_image


def label_number(text, prefix):
    text = text.strip().upper().replace(' ', '')
    if len(text) < 3 or text[0] != prefix or text[1] not in 'O0':
        return None
    number = text[2:].translate(str.maketrans({'I':'1', 'L':'1', 'O':'0'}))
    return int(number) if re.fullmatch(r'[1-9]\d?', number) else None


def center(word, axis):
    return word[axis] + word['width' if axis == 'x' else 'height']/2


def read_matrix(lines):
    words = [word for line in lines for word in line['words']]
    anchors = [word for word in words if re.fullmatch(r'C[O0][/\-]P[O0]', word['text'].upper())]
    for anchor in anchors:
        height = anchor['height']
        x, y = center(anchor,'x'), center(anchor,'y')
        header = sorted((word for word in words if center(word,'x') > x+anchor['width']/2
                         and abs(center(word,'y')-y) < height*.6), key=lambda word:word['x'])
        columns = []
        index = 0
        while index < len(header):
            word = header[index]
            token = word['text']
            position = center(word,'x')
            if index+1 < len(header):
                following = header[index+1]
                gap = following['x'] - word['x'] - word['width']
                if following['text'].isdigit() and 0 <= gap < height*.55 and label_number(token,'P'):
                    token += following['text']
                    position = (word['x']+following['x']+following['width'])/2
                    index += 1
            number = label_number(token,'P')
            if number is not None:
                columns.append((number,position))
            index += 1
        numbers = [number for number,_ in columns]
        if len(numbers)<2 or numbers != list(range(1,len(numbers)+1)) or numbers[-1]>12:
            continue
        rows = sorted((word for word in words if center(word,'y')>y+height
                       and abs(center(word,'x')-x)<anchor['width']/2 and label_number(word['text'],'C')),
                      key=lambda word:center(word,'y'))
        if not rows:
            continue
        row_y = [center(row,'y') for row in rows]
        gaps = [right-left for left,right in zip([y]+row_y,row_y)]
        pitch = median(gaps)
        if any(not .55*pitch <= gap <= 1.6*pitch for gap in gaps):
            continue
        row_labels = [label_number(row['text'],'C') for row in rows]
        if len(set(row_labels)) != len(row_labels):
            continue
        x_centers = [position for _,position in columns]
        boundaries = [(left+right)/2 for left,right in zip([x]+x_centers,x_centers)]
        right_edge = x_centers[-1]+(x_centers[-1]-x_centers[-2])/2
        mapping = {f'CO{number}':{} for number in row_labels}
        for word in words:
            wx, wy = center(word,'x'), center(word,'y')
            if not boundaries[0] <= wx < right_edge or not (y+row_y[0])/2 < wy <= row_y[-1]+pitch/2:
                continue
            row = min(range(len(rows)),key=lambda i:abs(row_y[i]-wy))
            col = sum(wx >= point for point in boundaries)-1
            if word['text'] in ('-', '–', '—', '0'):
                continue
            if word['text'] not in ('1','2','3') or f'PO{numbers[col]}' in mapping[f'CO{row_labels[row]}']:
                # Ambiguous OCR should fall through to the document reader.
                mapping = {}
                break
            mapping[f'CO{row_labels[row]}'][f'PO{numbers[col]}'] = int(word['text'])
        if any(mapping.values()):
            return mapping
    return None


def without_table_grid(image):
    from PIL import ImageChops, ImageOps

    grayscale = ImageOps.grayscale(image)
    ink = ImageOps.invert(grayscale).point(lambda shade: 255 if shade >= 128 else 0)
    grid = ink.copy()
    grid.paste(0,(0,0,*grid.size))
    for horizontal in (True, False):
        streaks = ink
        # Retain straight runs at least 64 pixels long, then restore their extent.
        shifts = [(step,0) if horizontal else (0,step) for step in (1,2,4,8,16,32)]
        for x,y in shifts:
            streaks = ImageChops.darker(streaks, ImageChops.offset(streaks,x,y))
        for x,y in shifts:
            streaks = ImageChops.lighter(streaks, ImageChops.offset(streaks,-x,-y))
        grid = ImageChops.lighter(grid,streaks)
    return ImageChops.lighter(grayscale,grid)


def read_mapping_image(path, document_id):
    """Return a mapping only when OCR can identify the table geometry."""
    from PIL import Image, ImageOps

    with Image.open(path) as raw:
        if raw.width*raw.height > 30_000_000:
            raise ValueError('Image exceeds 30 megapixels.')
        image = ImageOps.exif_transpose(raw)
        scale = min(2, 2600/max(image.size))
        image = image.resize(tuple(max(1,round(size*scale)) for size in image.size), Image.Resampling.LANCZOS)
        recognized = ocr_image(image)
    mapping = read_matrix(recognized['ocr_lines'])
    if mapping is None and os.environ.get('SCRUTINY_OCR') == 'tesseract':
        table = tesseract_image(without_table_grid(image),table=True)
        mapping = read_matrix(table['ocr_lines'])
        if mapping and table['text'] != recognized['text']:
            recognized['text'] = '\n'.join(filter(None, (recognized['text'],table['text'])))
    if mapping is None:
        return None
    pages = [{'page':1,'text':recognized['text'],'method':'mapping_ocr'}]
    metadata,_,_ = parse_proposals(pages,document_id)
    outcomes = parse_outcome_statements(pages)
    return pages,metadata,[],outcomes,mapping,['Compare the detected CO–PO cells with the original image. Unread CO statements can be entered manually.']
