export type ChecklistItem = {
  category: string;
  check: string;
  status: "PASS" | "FAIL" | "WARN" | string;
  detail: string;
};

export type QuestionItem = {
  q_no: string;
  question_text: string;
  allocated_marks: number;
  stated_co: string;
  stated_blooms: string;
  module?: string | null;
  is_or_choice?: boolean;
  or_group?: string | null;
  refers_to_figure?: boolean;
  has_diagram?: boolean;
};

export type QuestionAudit = {
  q_no: string;
  question_text: string;
  allocated_marks: number;
  stated_co: string;
  stated_blooms: string;
  is_in_syllabus: boolean;
  matched_syllabus_unit?: string | null;
  predicted_blooms: string;
  blooms_match: boolean;
  blooms_quality_verdict?: string | null;
  co_match: boolean;
  predicted_co?: string | null;
  is_duplicate: boolean;
  historical_overlap?: string | null;
  issues_found: string[];
  suggested_rewrite?: string | null;
  upgraded_rewrite?: string | null;
};

export type ScrutinyReport = {
  metadata: {
    course_code?: string | null;
    course_title?: string | null;
    semester?: string | null;
    cie_number?: string | null;
    date?: string | null;
    duration?: string | null;
    max_marks?: number | null;
    institution?: string | null;
    header_issues: string[];
  };
  parsed_questions: QuestionItem[];
  arithmetic_errors: string[];
  formatting_anomalies: string[];
  question_audits: QuestionAudit[];
  overall_rbt_distribution: Record<string, number>;
  rbt_counts?: Record<string, number>;
  co_coverage: Record<string, number>;
  hots_percentage: number;
  lots_percentage: number;
  checklist: ChecklistItem[];
  final_verdict: string;
  executive_summary: string;
  llm_used: boolean;
  paper_text?: string;
  syllabus_text?: string;
  allowed_units?: string[];
};
