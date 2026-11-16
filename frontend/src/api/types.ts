export type Role = "admin" | "expert" | "learner";
export type Verdict = "VERIFIED" | "UNCERTAIN" | "FAILED";

export interface User { id: string; email: string; full_name: string; role: Role; org_id: string }
export interface Page<T> { items: T[]; total: number; limit: number; offset: number }

export interface Skill {
  id: string; slug: string; title: string; summary: string; domain: string; difficulty: string;
  published_version_id: string | null; created_at: string;
}

export interface Issue { code: string; message: string; step_id: string | null; severity: string }
export interface ValidationReport { ok: boolean; errors: Issue[]; warnings: Issue[] }

export interface Version {
  id: string; version_number: number; status: "draft" | "in_review" | "published" | "archived";
  graph: SkillGraph; validation_report: ValidationReport; source_video_id: string | null;
  approved_by: string | null; approved_at: string | null; change_note: string; created_at: string;
}
export interface SkillDetail extends Skill { versions: Version[] }

export type Method =
  | { type: "visual"; criteria: { id: string; description: string; detector_labels?: string[] }[]; min_confidence?: number | null; camera_guidance?: string }
  | { type: "measurement"; quantity: string; unit: string; min: number | null; max: number | null; probe_points: string; negative_means_reversed_polarity?: boolean; tool?: string }
  | { type: "learner_confirmation"; prompt: string }
  | { type: "instructor_signoff"; prompt: string };

export interface Step {
  step_id: string; title: string; description: string; kind: string; instructions: string[];
  prerequisites: string[]; required_tools: string[]; required_components: string[]; expected_observations: string[];
  validation: { methods: Method[]; policy: "all" | "any" };
  safety: { critical: boolean; requirements: string[]; hazards: string[] };
  common_mistakes: { id: string; description: string; correction: string; safety_hazard: boolean }[];
  transitions: { to: string; condition: { type: string; method_index?: number | null; value?: number | null }; label: string }[];
  terminal: boolean; mandatory: boolean; reference_images: string[];
  evidence_refs: { video_id: string | null; t_start: number | null; t_end: number | null; transcript_excerpt: string }[];
  confidence: number | null; expert_annotations: { text: string }[];
}

export interface SkillGraph {
  schema: string; skill_id: string; title: string; version: string; difficulty: string; estimated_duration: number;
  summary: string; required_tools: string[]; required_components: string[]; entry_step: string; steps: Step[];
  provenance: { origin: string; source_video_id?: string | null; model?: string | null };
}

export type SessionState =
  | "CREATED" | "PREPARING" | "IN_PROGRESS" | "AWAITING_EVIDENCE" | "VALIDATING" | "VERIFIED" | "COMPLETED"
  | "NEEDS_CORRECTION" | "BLOCKED_BY_SAFETY" | "NEEDS_HUMAN_REVIEW" | "ABANDONED";

export interface LearningSession {
  id: string; skill_id: string; version_id: string; learner_id: string; mode: "guided" | "assessment";
  state: SessionState; current_step: string | null; path: string[]; verified_steps: string[];
  recording_consent: boolean; assistance_count: number; started_at: string | null; completed_at: string | null; created_at: string;
}

export interface MethodResult { method_index: number; method_type: string; verdict: Verdict; message: string; confidence: number | null; value: number | boolean | null }
export interface ValidationResult {
  id: string; step_key: string; verdict: Verdict; confidence: number | null; method_results: MethodResult[];
  message: string; detected_mistake_id: string | null; safety_violation: boolean; created_at: string;
}

export interface Briefing { requirements: string[]; hazards: string[]; scope: string }

export interface SessionView {
  session: LearningSession; current_step: Step | null; last_validation: ValidationResult | null; briefing: Briefing;
  skill: { title: string; entry_step: string; steps: { step_id: string; title: string; critical: boolean; terminal: boolean }[] };
}

export interface EvidenceResult {
  validation: ValidationResult; session: LearningSession; next_action: string | null;
  detections?: { label: string; confidence: number }[] | null;
  observations?: { criterion_id: string; status: string; confidence: number; note: string }[] | null;
}

export interface Ratio { numerator: number; denominator: number; value: number | null }
export interface Report {
  id: string; session_id: string; learner_id: string; skill_id: string; version_id: string; mode: string;
  session_level: string; rule_trace: { criterion: string; passed: boolean; detail: string }[]; narrative: string; created_at: string;
  metrics: {
    completed: boolean; task_completion: Ratio; correct_sequence: Ratio; safety_compliance: Ratio; tool_selection: Ratio;
    recovery: Ratio; mistakes: number; mistake_ids: string[]; safety_violations: number; assistance_requests: number;
    instructor_signoffs: number; uncertain_validations: number; out_of_sequence_attempts: number;
    duration_minutes: number | null; estimated_minutes: number; path: string[]; branches_taken: string[];
  };
}

export interface Competency {
  skill_id: string; level: string; attempts: number; completions: number; updated_at: string;
  evidence: { guided_completions: number; independent_completions: number; first_attempt_success: boolean; basis: string; criteria: Record<string, string> };
}

export interface Video { id: string; title: string; original_filename: string; content_type: string; size_bytes: number; duration_s: number | null; created_at: string }
export interface Job { id: string; video_id: string; kind: string; status: "queued" | "running" | "succeeded" | "failed"; stage: string; progress: number; result: Record<string, unknown>; error: string | null; created_at: string }
export interface Capabilities { ai: boolean; ffmpeg: boolean; detector: { available: boolean; reason: string | null } }
