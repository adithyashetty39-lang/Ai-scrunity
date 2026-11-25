"""Resolve uploaded syllabus scope without discarding page provenance."""
from dataclasses import dataclass, field
import re


def topic_pattern(phrase):
    words=re.findall(r'\w+',phrase)
    return r'\b'+r'\W+'.join(re.escape(word) for word in words)+r'\b' if words else None


def range_span(text,start,end):
    left_pattern,right_pattern=topic_pattern(start),topic_pattern(end)
    if not left_pattern or not right_pattern:return None
    left=re.search(left_pattern,text,re.I)
    if left is None:return None
    right=re.search(right_pattern,text[left.start():],re.I)
    if right is None:return None
    return left.start(), left.start()+right.end()


def covered_range(text,start,end):
    span = range_span(text,start,end)
    return text[slice(*span)] if span is not None else None


@dataclass
class ResolvedCoverage:
    included: dict[str, str] = field(default_factory=dict)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    error: str | None = None

    def add(self, section, text, start, end):
        if text[start:end].strip():
            self.included[section] = text[start:end]
        excerpts = [part for part in (text[:start], text[end:]) if part.strip()]
        if excerpts:
            self.excluded[section] = excerpts


def resolve_coverage(profile):
    result = ResolvedCoverage()
    sections = profile.syllabus
    if not any(text.strip() for text in sections.values()):
        result.error = 'Upload a readable syllabus sheet or module before evaluating.'
        return result
    if not profile.material_coverage:
        # Compatibility for saved drafts created before page-specific ranges.
        text = '\n'.join(sections.values())
        span = (0, len(text)) if profile.coverage_mode == 'all_uploaded' else range_span(text, profile.coverage_start, profile.coverage_end)
        if span is None:
            result.error = 'The coverage topics could not be located in order. Choose a range on the uploaded source.'
            return result
        start, end = span
        offset = 0
        for section, page in sections.items():
            lower = min(len(page), max(0, start-offset))
            upper = min(len(page), max(lower, end-offset))
            result.add(section, page, lower, upper)
            offset += len(page)+1
        return result

    for index, document in enumerate(profile.syllabus_document_ids, 1):
        choice = profile.material_coverage.get(document)
        label = f'Module {choice.module}' if choice and choice.module else choice.filename if choice and choice.filename else f'Source {index}'
        if choice is None or (profile.material_kind == 'notes' and choice.module is None):
            return ResolvedCoverage(error=f'{label}: choose the module number and coverage for this file.')
        page_keys = {int(section.removeprefix(document+':page ')): section for section in sections
                     if section.startswith(document+':page ') and section.removeprefix(document+':page ').isdigit()}
        if not page_keys:
            return ResolvedCoverage(error=f'{label}: no readable source pages were found.')
        if choice.mode == 'entire':
            first, last = min(page_keys), max(page_keys)
            start, end = 0, len(sections[page_keys[last]])
        else:
            first, last = choice.start_page, choice.end_page
            if first not in page_keys or last not in page_keys or first > last:
                return ResolvedCoverage(error=f'{label}: enter valid start and end PDF page numbers in order.')
            left, right = topic_pattern(choice.start_topic), topic_pattern(choice.end_topic)
            if not left or not right:
                return ResolvedCoverage(error=f'{label}: enter both topic boundary phrases.')
            first_text, last_text = sections[page_keys[first]], sections[page_keys[last]]
            starts = list(re.finditer(left, first_text, re.I))
            ends = list(re.finditer(right, last_text, re.I))
            if not starts:
                return ResolvedCoverage(error=f'{label}: starting phrase “{choice.start_topic}” was not found on page {first}. Copy it from the extracted text.')
            if not ends:
                return ResolvedCoverage(error=f'{label}: ending phrase “{choice.end_topic}” was not found on page {last}. Copy it from the extracted text.')
            if first == last:
                starts = [match for match in starts if match.start() <= ends[-1].start()]
                if starts:
                    ends = [match for match in ends if match.start() >= starts[0].start()]
            if not starts:
                return ResolvedCoverage(error=f'{label}: the ending topic comes before the starting topic.')
            if len(starts)>1:
                return ResolvedCoverage(error=f'{label}: starting phrase “{choice.start_topic}” occurs {len(starts)} times on page {first}. Include nearby words to identify the intended occurrence.')
            if len(ends)>1:
                return ResolvedCoverage(error=f'{label}: ending phrase “{choice.end_topic}” occurs {len(ends)} times on page {last}. Include nearby words to identify the intended occurrence.')
            start, end = starts[0].start(), ends[0].end()
        if any(number not in page_keys or not sections[page_keys[number]].strip() for number in range(first,last+1)):
            return ResolvedCoverage(error=f'{label}: a selected page has no readable text. Check the source or upload a clearer copy.')
        for number, section in sorted(page_keys.items()):
            page = sections[section]
            if first <= number <= last:
                result.add(section, page, start if number == first else 0, end if number == last else len(page))
            else:
                result.add(section, page, 0, 0)
    if not result.included:
        result.error = 'Select at least one readable portion of an uploaded source.'
    return result
