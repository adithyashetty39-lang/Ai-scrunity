import { isPrintedLevel, readPrintedMarks, type PrintedAllocation } from './BloomDistributionPreview';
import type { SourceCoverage } from './MaterialCoverage';

export type ReviewStage = 'papers' | 'mapping' | 'syllabus' | 'results';
type PaperSet = 'A' | 'B';
export type ReviewTarget = { stage: ReviewStage; id: string; reason: string; set?: PaperSet };
type ReviewQuestion = PrintedAllocation & { q_no: string; text: string; co: string[]; po: string[] };
type ReviewPaper = { label: PaperSet; questions: ReviewQuestion[]; document_ids: string[] };
type CoverageField = 'module' | 'start-page' | 'end-page' | 'start-topic' | 'end-topic';

export const questionFieldId = (index: number, field: string) => `review-question-${index}-${field}`;
export const coverageFieldId = (index: number, field: CoverageField) => `review-coverage-${index}-${field}`;
export const outcomeFieldId = (co: string, field: 'statement' | 'strengths') => `review-outcome-${field}-${co}`;
export const facultyDecisionId = (index: number) => `review-faculty-${index}`;

export function missingCoverageField(selection: SourceCoverage, notes: boolean): CoverageField | null {
  if (notes && !selection.module) return 'module';
  if (selection.mode === 'entire') return null;
  if (!selection.start_page) return 'start-page';
  if (!selection.end_page || selection.end_page < selection.start_page) return 'end-page';
  if (!selection.start_topic?.trim()) return 'start-topic';
  if (!selection.end_topic?.trim()) return 'end-topic';
  return null;
}

const coverageInstructions: Record<CoverageField, string> = {
  module: 'Enter the module number',
  'start-page': 'Choose the start page',
  'end-page': 'Choose an end page at or after the start page',
  'start-topic': 'Enter the starting topic phrase',
  'end-topic': 'Enter the ending topic phrase',
};

function paperTask({ label, questions }: ReviewPaper): ReviewTarget | null {
  const set = label;
  const repeatedIndex = questions.findIndex((question, index) =>
    questions.findIndex(({ q_no }) => q_no === question.q_no) !== index);
  if (repeatedIndex !== -1) return {
    stage: 'papers', set, id: questionFieldId(repeatedIndex, 'number'),
    reason: `Resolve the repeated Set ${set} question ${questions[repeatedIndex].q_no}.`,
  };
  for (const [index, question] of questions.entries()) {
    const location = `Set ${set}, question ${question.q_no}`;
    if (!question.text.trim()) return {
      stage: 'papers', set, id: questionFieldId(index, 'text'),
      reason: `Enter the text for ${location}.`,
    };
    if (readPrintedMarks(question.marks) === null) return {
      stage: 'papers', set, id: questionFieldId(index, 'marks'),
      reason: `Confirm the printed marks for ${location}.`,
    };
    if (!isPrintedLevel(question.stated_level)) return {
      stage: 'papers', set, id: questionFieldId(index, 'bloom'),
      reason: `Confirm the printed Bloom’s level for ${location}.`,
    };
    if (!question.co.length || !question.po.length) return {
      stage: 'papers', set, id: questionFieldId(index, question.co.length ? 'po' : 'co'),
      reason: `Confirm the printed CO and PO labels for ${location}.`,
    };
  }
  return null;
}

type ReviewInputs = {
  papers: ReviewPaper[];
  canContinue: boolean;
  pendingKind?: PaperSet | 'mapping' | 'syllabus';
  cloud: 'ready' | 'consent' | 'unavailable';
  outcomes: Record<string, string>;
  coPo: Record<string, Record<string, number>>;
  rulesConfirmed: boolean;
  selections: SourceCoverage[];
  notes: boolean;
  uploadModule: number;
  coverageConfirmed: boolean;
  coverageFailure: string;
  hasAudit: boolean;
  findings: { set_label: PaperSet; q_no: string; faculty_level: string; faculty_bloom_decision?: { action: string } | null }[];
  blockerCount: number;
};

export function nextReviewTarget(input: ReviewInputs): ReviewTarget {
  const setA = input.papers.find(paper => paper.label === 'A');
  const cloudTask = input.cloud === 'consent'
    ? { id: 'review-cloud-consent', reason: 'Confirm cloud processing for this scrutiny.' }
    : { id: 'review-processing', reason: 'Check the processing settings before continuing.' };
  if (input.pendingKind && (input.canContinue || ['A', 'B'].includes(input.pendingKind))) {
    const kind = input.pendingKind;
    const task = input.cloud === 'ready'
      ? { id: 'review-upload-read', reason: 'Upload and read the file you selected.' }
      : cloudTask;
    if (kind === 'A' || kind === 'B') return { ...task, stage: 'papers', set: kind };
    return { ...task, stage: kind };
  }
  if (!setA?.questions.length) return setA?.document_ids.length
    ? { stage: 'papers', set: 'A', id: 'review-add-question', reason: 'Check the source or add the first Set A question.' }
    : { stage: 'papers', set: 'A', id: 'review-paper-file', reason: 'Upload your Set A question paper.' };

  const paperTasks = [setA, ...input.papers.filter(paper => paper.label === 'B')];
  for (const paper of paperTasks) {
    if (!paper.questions.length && paper.document_ids.length) return {
      stage: 'papers', set: paper.label, id: 'review-optional-set',
      reason: 'Review the empty Set B extraction. Add its questions or remove the optional set.',
    };
    const task = paperTask(paper);
    if (task) return task;
  }

  const outcomes = new Set(paperTasks.flatMap(paper => paper.questions.flatMap(question => question.co)));
  for (const co of outcomes) {
    if (!input.outcomes[co]?.trim()) return {
      stage: 'mapping', id: outcomeFieldId(co, 'statement'), reason: `Enter the course outcome statement for ${co}.`,
    };
    if (!Object.keys(input.coPo[co] ?? {}).length) return {
      stage: 'mapping', id: outcomeFieldId(co, 'strengths'), reason: `Enter the PO strengths for ${co}.`,
    };
  }
  if (!input.rulesConfirmed) return {
    stage: 'mapping', id: 'review-rules', reason: 'Confirm the examination pattern and Bloom’s targets.',
  };
  if (!input.selections.length) return {
    stage: 'syllabus',
    id: input.notes && (!Number.isInteger(input.uploadModule) || input.uploadModule < 1)
      ? 'review-module-upload-number' : 'review-syllabus-file',
    reason: input.notes ? 'Add the first module file.' : 'Upload the syllabus or module material.',
  };
  for (const [index, selection] of input.selections.entries()) {
    const field = missingCoverageField(selection, input.notes);
    if (field) return {
      stage: 'syllabus', id: coverageFieldId(index, field),
      reason: `${coverageInstructions[field]} for ${selection.module ? `Module ${selection.module}` : `source ${index + 1}`}.`,
    };
  }
  if (input.coverageFailure) return {
    stage: 'syllabus', id: 'review-coverage-feedback', reason: 'Fix the coverage issue reported by scrutiny.',
  };
  if (!input.coverageConfirmed) return {
    stage: 'syllabus', id: 'review-coverage-confirm', reason: 'Confirm the selected syllabus coverage.',
  };
  if (input.cloud !== 'ready') return { ...cloudTask, stage: 'syllabus' };
  if (!input.hasAudit) return {
    stage: 'syllabus', id: 'review-evaluate', reason: 'Evaluate the current draft.',
  };
  const pending = input.findings.findIndex(question =>
    question.faculty_level === 'Unresolved' && question.faculty_bloom_decision?.action !== 'deferred');
  const index = pending >= 0 ? pending : input.findings.findIndex(question => question.faculty_level === 'Unresolved');
  if (index >= 0) {
    const { set_label, q_no } = input.findings[index];
    return {
      stage: 'results', id: facultyDecisionId(index),
      reason: `${pending >= 0 ? 'Record' : 'Revisit'} the faculty Bloom’s decision for Set ${set_label}, question ${q_no}.`,
    };
  }
  if (input.blockerCount > 0) return {
    stage: 'results', id: 'review-report-checks', reason: 'Open the remaining draft report checks.',
  };
  return { stage: 'results', id: 'review-download', reason: 'The draft PDF is available.' };
}
