import { coverageFieldId } from './reviewNavigation';

export type SourceCoverage = {
  filename?: string;
  module: number | null;
  mode: 'entire' | 'range';
  start_page?: number | null;
  end_page?: number | null;
  start_topic?: string;
  end_topic?: string;
};

type Props = {
  index: number;
  label: string;
  notes: boolean;
  selection: SourceCoverage;
  pages: {number: number; text: string}[];
  onChange: (selection: SourceCoverage) => void;
  onOpen: () => void;
  onRemove: () => void;
};

export function MaterialCoverage({index, label, notes, selection, pages, onChange, onOpen, onRemove}: Props) {
  const update = (fields: Partial<SourceCoverage>) => onChange({...selection, ...fields});
  const pageOptions = pages.map(page => <option key={page.number} value={page.number}>Page {page.number}</option>);

  return <article className="question">
    <div className="subheading">
      <h3>{label}</h3>
      <div className="source-links">
        <button className="text-button" onClick={onOpen}>View original</button>
        <button className="remove" onClick={onRemove}>Remove source</button>
      </div>
    </div>
    <div className="metadata-grid">
      {notes && <label>Module number
        <input id={coverageFieldId(index, 'module')} type="number" min="1" step="1" value={selection.module ?? ''}
          onChange={e => update({module:Number.isInteger(e.target.valueAsNumber) && e.target.valueAsNumber >= 1 ? e.target.valueAsNumber : null})}/>
      </label>}
      <label>Coverage
        <select value={selection.mode} onChange={e => update({mode:e.target.value as SourceCoverage['mode']})}>
          <option value="entire">{notes ? 'Entire module file' : 'Entire syllabus file'}</option>
          <option value="range">Page and topic range</option>
        </select>
      </label>
      {selection.mode === 'range' && <>
        <label>Start page<select id={coverageFieldId(index, 'start-page')} value={selection.start_page ?? ''}
          onChange={e => update({start_page:Number(e.target.value) || null})}>
          <option value="">Choose a page</option>{pageOptions}</select></label>
        <label>Starting topic phrase<input id={coverageFieldId(index, 'start-topic')} value={selection.start_topic ?? ''} maxLength={300}
          onChange={e => update({start_topic:e.target.value})} placeholder="Copy the start from the selected page"/></label>
        <label>End page<select id={coverageFieldId(index, 'end-page')} value={selection.end_page ?? ''}
          onChange={e => update({end_page:Number(e.target.value) || null})}>
          <option value="">Choose a page</option>{pageOptions}</select></label>
        <label>Ending phrase<input id={coverageFieldId(index, 'end-topic')} value={selection.end_topic ?? ''} maxLength={300}
          onChange={e => update({end_topic:e.target.value})} placeholder="Copy the last words to include"/></label>
      </>}
    </div>
    <details><summary>Extracted text by page</summary>
      {pages.map(page => <div key={page.number}><b>Page {page.number}</b><pre className="syllabus-text">{page.text || 'No readable text on this page.'}</pre></div>)}
    </details>
  </article>;
}

