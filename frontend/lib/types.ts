export type Template = {
  transfer_day: number; max_transfers: number; check_day: number; collection_day: number;
  collection_days: number; stock_interval: number; watch_day: number; windows: string[][];
  rate18: number; virgin_hours25: number; virgin_hours18: number;
};
export type Culture = {
  id: string; label: string; kind: 'vial' | 'bottle' | 'petri_dish' | 'egg_laying'; purpose: 'stock' | 'cross' | 'virgin' | 'egg_laying' | 'dissection' | 'imaging' | 'other';
  genotype: string; female_genotype: string; male_genotype: string; setup_date: string; setup_time: string | null;
  initial_temperature: number; temperature: number; temperature_policy: string; notes: string; template: Template;
  cohort_id: string; transfer_index: number; source_id: string | null; parents: string; stage: string; status: string;
  calendar_day: number; effective_age: number; temperatures: {at: string; temperature: number}[];
  logs: {id: string; at: string; action: string; notes: string}[];
  clock: {state: string; last_clear: string | null; deadline: string | null};
  incubation?: Incubation | null; egg_batch_id?: string | null;
  source_relation?: 'egg_laying_transfer' | 'egg_laying_generation' | 'egg_laying_parents' | 'egg_laying_offspring';
  adult_source?: 'parents' | 'offspring';
  eclosion_estimate?: EclosionEstimate | null; source_eclosion_estimate?: EclosionEstimate | null;
  genotype_review_required?: boolean; setup_time_review_required?: boolean;
  workflow?: Workflow | null; first_eclosion_at?: string;
  incubation_window?: {start: string; end: string; review: boolean}; egg_age_hours?: number[];
};
export type Workflow = {cross_goal: 'score' | 'virgins'; transfer_enabled: boolean; remove_day: number; selection_day: number; selection_days: number; selection_window: string[]; target_genotype: string; selection_notes: string; female_virgins: 'unconfirmed' | 'confirmed'; follow_eclosion: boolean};
export type EclosionEstimate = {at: string; basis: 'observed' | 'estimated'; source_planned: boolean; date_only?: boolean};
export type Incubation = {lay_start: string; lay_end: string; min_hours: number; max_hours: number; reference_temperature: number; lay_temperature: number};
export type EggBatch = {id: string; label: string; source_id: string; lay_start: string; lay_end: string; genotype: string; temperature: number; notes: string; status: 'planned' | 'collected' | 'cancelled'; collected_at: string | null; uses: {id: string; at: string; purpose: string; notes: string}[]};
export type Task = {
  id: string; container_id: string | null; rule_key: string; kind: string; due: string; end: string;
  critical: boolean; basis: string; title: string; status: string; pinned: boolean; conflict: boolean;
  egg_batch_id?: string | null; batch_label?: string;
  timing_review?: boolean;
};
export type Availability = {date: string; kind: string; windows: string[][]; notes: string};
export type Settings = {locale: string; timezone: string; weekly: Record<string, string[][]>; template: Template};
export type AppState = {containers: Culture[]; events: Task[]; settings: Settings; availability: Availability[]; now: string; plans: unknown[]; egg_batches: EggBatch[]};
export type Suggestion = {cold_at: string; warm_at: string; hours: number; collection_date: string; events: Task[]; setup_at?: string};
export type Suggestions = {state: string; options: Suggestion[]; resolution_minutes?: number};
