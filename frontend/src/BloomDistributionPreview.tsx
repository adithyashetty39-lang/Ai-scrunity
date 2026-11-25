const bands = [
  { key: 'L1-L2', label: 'L1–L2' },
  { key: 'L3-L4', label: 'L3–L4' },
  { key: 'L5-L6', label: 'L5–L6' },
] as const;

export type PrintedAllocation = {
  marks: number | string | null;
  stated_level: number | null;
};

export function readPrintedMarks(value: PrintedAllocation['marks']) {
  const marks = Number(value);
  return Number.isFinite(marks) && marks > 0 && marks <= 10 ? marks : null;
}

export function isPrintedLevel(value: number | null): value is number {
  return value != null && Number.isInteger(value) && value >= 1 && value <= 6;
}

const format = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });

type Props = {
  setLabel: 'A' | 'B';
  questions: PrintedAllocation[];
  offeredMarks: number | string;
  bloomTargets: Record<string, number | string>;
};

export function BloomDistributionPreview({ setLabel, questions, offeredMarks, bloomTargets }: Props) {
  const offered = Number(offeredMarks);
  if (!questions.length || !Number.isFinite(offered) || offered <= 0 || !bloomTargets) return null;

  const grouped = [0, 0, 0];
  let entered = 0;
  let unplaced = 0;
  let missingMarks = 0;
  let missingLevels = 0;
  for (const { marks: value, stated_level: level } of questions) {
    const marks = readPrintedMarks(value);
    if (!isPrintedLevel(level)) missingLevels++;
    if (marks === null) {
      missingMarks++;
      continue;
    }
    entered += marks;
    if (isPrintedLevel(level)) grouped[Math.floor((level - 1) / 2)] += marks;
    else unplaced += marks;
  }

  return <section className="bloom-preview" aria-labelledby="bloom-preview-heading">
    <div className="bloom-preview-heading">
      <h3 id="bloom-preview-heading">Bloom’s distribution preview</h3>
      <span>Set {setLabel}</span>
    </div>
    <p>Uses the {format.format(offered)} printed marks, including both sides of each choice.</p>
    <dl className="bloom-bands">
      {bands.map(({ key, label }, index) => {
        const marks = grouped[index];
        const percent = 100 * marks / offered;
        const target = Number(bloomTargets[key]);
        return <div className="bloom-band" key={key}>
          <dt>{label}</dt>
          <dd>
            <div className="bloom-bar" aria-hidden="true">
              <span style={{ width: `${Math.min(percent, 100)}%` }}/>
              <i style={{ left: `${Math.min(target, 100)}%` }} />
            </div>
            <div className="bloom-band-values">
              <strong>{format.format(marks)} marks ({format.format(percent)}%)</strong>
              <span>Target {format.format(target * offered / 100)} marks ({format.format(target)}%)</span>
            </div>
          </dd>
        </div>;
      })}
    </dl>
    <p className="bloom-preview-note">
      {format.format(entered)} of {format.format(offered)} marks entered.
      {entered > offered && ' The entered marks exceed the paper total.'}
      {missingMarks > 0 && ` Missing or invalid marks in ${missingMarks} question ${missingMarks === 1 ? 'part' : 'parts'}.`}
      {missingLevels > 0 && ` Missing printed Bloom’s levels in ${missingLevels} question ${missingLevels === 1 ? 'part' : 'parts'}.`}
      {unplaced > 0 && ` ${format.format(unplaced)} marks are still unclassified.`}
    </p>
  </section>;
}
