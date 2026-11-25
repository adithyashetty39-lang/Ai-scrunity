import { useEffect, useState } from 'react';

type Band = 'L1-L2' | 'L3-L4' | 'L5-L6';
type Totals = Record<Band, number | string>;
type Choice = {
  q_no: string; marks: number | string; from_band: Band; to_band: Band; levels: number[];
  after: Totals; remaining_marks: number | string;
};
type Plan = { before: Totals; target: Totals; offered_marks: number | string; options: Choice[] };
type Suggestion = {
  question: string; level: number; marks: number | string;
  evidence: { filename: string; page: number; quote: string };
  bloom_reason: string; coverage_reason: string; mapping_checked: boolean;
  marking_points: { expected: string; marks: number | string }[];
};
type Props = {
  recordId: string; revision: number; setLabel: 'A' | 'B';
  request: (path: string, options?: RequestInit) => Promise<Response>;
  disabled: boolean;
};

const bands: Band[] = ['L1-L2', 'L3-L4', 'L5-L6'];
const levels = ['Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create'];
const pretty = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const marks = (value: number | string) => pretty.format(Number(value));
const bandLabel = (key: Band) => key.replace('-', '–');
const message = (error: unknown) => error instanceof Error ? error.message : 'The replacement check failed.';

export function BloomReplacement({ recordId, revision, setLabel, request, disabled }: Props) {
  const [plan, setPlan] = useState<Plan | null>(null);
  const [choiceIndex, setChoiceIndex] = useState(0);
  const [level, setLevel] = useState(0);
  const [strategy, setStrategy] = useState('same_topic');
  const [job, setJob] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [suggestion, setSuggestion] = useState<Suggestion | null>(null);
  const [copyStatus, setCopyStatus] = useState('');
  const path = `/submissions/${recordId}/bloom-replacements`;
  const choice = plan?.options[choiceIndex];
  const busy = disabled || loading || job !== null;

  useEffect(() => {
    if (!job) return;
    const controller = new AbortController();
    let timer: number;
    async function poll() {
      try {
        const result = await (await request(`${path}/${job}`, { signal: controller.signal })).json();
        if (controller.signal.aborted) return;
        if (result.status === 'checking') {
          timer = window.setTimeout(poll, 2200);
          return;
        }
        setSuggestion(result.suggestion);
        setJob(null);
      } catch (error) {
        if (!controller.signal.aborted) {
          setError(message(error));
          setJob(null);
        }
      }
    }
    void poll();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [job, path, request]);

  async function loadPlan() {
    setError('');
    setLoading(true);
    try {
      const result: Plan = await (await request(`${path}?revision=${revision}&set_label=${setLabel}`)).json();
      setPlan(result);
      setLevel(result.options[0]?.levels[0] ?? 0);
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }

  async function generate() {
    if (!choice) return;
    setSuggestion(null);
    setCopyStatus('');
    setError('');
    setLoading(true);
    try {
      const result = await (await request(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ revision, set_label: setLabel, q_no: choice.q_no, target_level: level, strategy }),
      })).json();
      setJob(result.job_id);
    } catch (error) {
      setError(message(error));
    } finally {
      setLoading(false);
    }
  }

  function clearSuggestion() {
    setSuggestion(null);
    setCopyStatus('');
    setError('');
  }

  return <section className="bloom-replacement">
    <div className="bloom-preview-heading">
      <h3>Bloom’s replacement options</h3><span>Set {setLabel}</span>
    </div>
    <p>Optional. Use this to explore possible replacements for your paper.</p>
    {!plan && <button type="button" className="secondary" disabled={busy} onClick={() => void loadPlan()}>
      {loading ? 'Calculating…' : 'Plan a replacement'}
    </button>}
    {plan && <>
      <p>Projection uses all {marks(plan.offered_marks)} printed marks and the printed Bloom’s labels.</p>
      {choice && <div className="metadata-grid">
        <label>Question to replace<select value={choiceIndex} disabled={busy} onChange={event => {
          const index = Number(event.target.value);
          setChoiceIndex(index);
          setLevel(plan.options[index].levels[0]);
          clearSuggestion();
        }}>
          {plan.options.map((item, index) => <option key={`${item.q_no}/${item.to_band}`} value={index}>
            Q{item.q_no} · {marks(item.marks)} marks → {bandLabel(item.to_band)}
          </option>)}
        </select></label>
        <label>Target Bloom’s level<select value={level} disabled={busy} onChange={event => {
          setLevel(Number(event.target.value));
          clearSuggestion();
        }}>
          {choice.levels.map(item => <option value={item} key={item}>L{item} · {levels[item - 1]}</option>)}
        </select></label>
        <label>Replacement topic<select value={strategy} disabled={busy} onChange={event => {
          setStrategy(event.target.value);
          clearSuggestion();
        }}>
          <option value="same_topic">Rewrite on the same topic</option>
          <option value="different_topic">Choose another covered topic</option>
        </select></label>
      </div>}
      <table className="bloom-replacement-totals">
        <caption className="sr-only">Bloom’s allocation in marks for Set {setLabel}</caption>
        <thead><tr><th scope="col">Bloom’s band</th><th scope="col">Before</th>
          {choice && <th scope="col">After</th>}<th scope="col">Target</th></tr></thead>
        <tbody>{bands.map(key => <tr key={key}><th scope="row">{bandLabel(key)}</th><td>{marks(plan.before[key])}</td>
          {choice && <td>{marks(choice.after[key])}</td>}<td>{marks(plan.target[key])}</td></tr>)}</tbody>
      </table>
      {choice ? <>
        <p>{Number(choice.remaining_marks) === 0
          ? 'This replacement would meet all three printed targets.'
          : `This would improve the allocation. ${marks(choice.remaining_marks)} marks would still fall short across the target bands.`}</p>
        <button type="button" className="secondary" disabled={busy} onClick={() => void generate()}>Suggest replacement</button>
        {(loading || job) && <p role="status">Drafting and checking the question against the covered material…</p>}
      </> : <p>With the current marks, no single question replacement improves the allocation.</p>}
    </>}
    {error && <p className="alert" role="alert">{error}</p>}
    {suggestion && <div className="bloom-replacement-suggestion">
      <h4>Proposed question · L{suggestion.level} · {marks(suggestion.marks)} marks</h4>
      <p>{suggestion.question}</p>
      <p><b>Why this level fits</b> {suggestion.bloom_reason}</p>
      <p><b>Why it fits the coverage</b> {suggestion.coverage_reason}</p>
      <details>
        <summary>Evidence · {suggestion.evidence.filename}, page {suggestion.evidence.page}</summary>
        <q>{suggestion.evidence.quote}</q>
      </details>
      <details>
        <summary>Suggested answer and marking points</summary>
        <ul>{suggestion.marking_points.map((point, index) =>
          <li key={index}>{point.expected} ({marks(point.marks)} marks)</li>)}</ul>
      </details>
      <p>{suggestion.mapping_checked ? 'Confirm the existing CO–PO mapping before use.'
        : 'The available CO–PO mapping needs faculty confirmation.'} Review the wording before editing the paper.</p>
      <button type="button" className="secondary" onClick={() => {
        if (!navigator.clipboard) {
          setCopyStatus('Select the question text to copy it.');
          return;
        }
        void navigator.clipboard.writeText(suggestion.question).then(
          () => setCopyStatus('Question copied.'),
          () => setCopyStatus('Select the question text to copy it.'),
        );
      }}>Copy question</button>
      {copyStatus && <span className="bloom-copy-status" role="status">{copyStatus}</span>}
    </div>}
  </section>;
}
