/* Shapes returned by phewas_server API v1 (mirrors phewas_core.query / manifest). */

export type Stat = "or" | "p" | "beta" | "se" | "cases" | "case_carriers" | "controls" | "ctrl_carriers" | "aaf" | "mac";
export const STATISTICS: Stat[] = ["or", "p", "beta", "se", "cases", "case_carriers", "controls", "ctrl_carriers", "aaf", "mac"];

export interface Cohort {
  id: string;
  label: string;
  is_meta: boolean;
  primary: boolean;
}

export interface FieldDef {
  name: string;
  type: "str" | "num" | "int" | "bool";
  label: string;
  group: string;
  fmt: string;
  table: boolean;
  filter: "" | "min" | "max" | "eq" | "in" | "text";
  structural: boolean;
}

export interface Source {
  role: string;
  path: string;
  sha256: string | null;
  bytes: number | null;
  rows: number | null;
  profile: string | null;
}

export interface Manifest {
  id: string;
  name: string;
  created: string;
  app_version: string;
  duckdb_version: string;
  cohorts: Cohort[];
  statistics: Stat[];
  dictionary: { id: string; label: string };
  annotation_fields: string[];
  sources: Source[];
  stats: Record<string, number>;
  build: string | null;
  notes: string;
  warnings: string[];
  manifest_version: number;
  schema_version: number;
}

export interface LibraryEntry {
  id: string;
  name: string;
  created: string;
  build: string | null;
  notes: string;
  cohorts: Cohort[];
  dictionary: { id: string; label: string };
  stats: Record<string, number>;
  warnings: string[];
  sources: Source[];
  size_bytes: number;
}

export interface Library {
  datasets: LibraryEntry[];
  current: string | null;
  home: string;
}

export interface GeneSummary {
  gene: string;
  chrom: string | null;
  min_pos: number | null;
  max_pos: number | null;
  n_variants: number;
  min_p: number | null;
  top_variant: string | null;
  top_trait: string | null;
  top_trait_desc: string | null;
}

export interface Meta {
  genes: GeneSummary[];
  stats: { n_variants: number; n_genes: number; n_traits: number; n_assoc: number };
  cohorts: Cohort[];
  primary_cohort: string;
  statistics: Stat[];
  fields: FieldDef[];
  manifest: Manifest | null;
}

export interface DatasetInfo {
  id: string;
  manifest: Manifest | null;
  cohorts: Cohort[];
  fields: FieldDef[];
  primary_cohort: string;
  dir: string;
  log: string;
}

export interface SearchResult {
  type: "gene" | "variant";
  id: string;
  gene?: string;
  label: string;
}

/** A gene-page row: variant_index columns + coordinates + every annotation field. */
export interface VariantRow {
  variant_id: string;
  gene: string;
  n_traits: number;
  min_p: number | null;
  top_trait: string | null;
  top_or: number | null;
  n_carriers: number | null;
  cohorts: string[];
  top_trait_desc: string | null;
  chrom: string | null;
  pos: number | null;
  ref: string | null;
  alt: string | null;
  [field: string]: unknown;
}

export interface GenePage {
  summary: GeneSummary;
  variants: VariantRow[];
}

export type CohortStats = Partial<Record<Stat, number | null>>;

export interface Association {
  trait: string;
  description: string | null;
  category: string | null;
  category_ord: number | null;
  color: string | null;
  cohorts: Record<string, CohortStats>;
}

export interface VariantPage {
  variant_id: string;
  gene: string;
  genes_for_variant: string[];
  variant: { chrom: string | null; pos: number | null; ref: string | null; alt: string | null } | null;
  annotation: Record<string, unknown> | null;
  primary_cohort: string;
  cohort_ids: string[];
  associations: Association[];
}

export interface InspectSumstats {
  path: string;
  exists: boolean;
  bytes?: number;
  header?: string[];
  profile?: string | null;
  profile_label?: string | null;
  kind?: string | null;
  cohorts?: { id: string; label: string; is_meta: boolean; statistics: string[] }[];
  preview?: Record<string, string>[];
  problems: string[];
}

export interface InspectAnnotation {
  path: string;
  exists: boolean;
  bytes?: number;
  header?: string[];
  fields_covered?: string[];
  n_fields_total?: number;
  problems: string[];
}

export interface Job {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  step: string;
  done: number;
  total: number;
  message: string;
  error: string | null;
  result: { dataset_id: string; name: string; seconds: number; stats: Record<string, number> } | null;
  warnings: string[];
  created: number;
  started: number | null;
  finished: number | null;
  seq: number;
  request: Record<string, unknown>;
}

export interface FsEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number | null;
  mtime: number;
}

export interface FsListing {
  path: string;
  parent: string | null;
  roots: string[];
  entries: FsEntry[];
}

export interface ProfileInfo {
  name: string;
  label: string;
  kind: string;
  source: string | null;
}

export interface DictionaryInfo {
  id: string;
  label: string;
  path: string;
  kind: string;
}
