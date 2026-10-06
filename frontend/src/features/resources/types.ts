export type PaginationStrategy = "none" | "page" | "offset" | "cursor";
export type ResourceSource = "manual" | "openapi";

export interface EndpointSpec {
  method: string;
  path: string;
}

export interface PaginationConfig {
  strategy: PaginationStrategy;
  page_param: string;
  size_param: string;
  first_page: number;
  total_pages_path: string | null;
  offset_param: string;
  limit_param: string;
  total_path: string | null;
  cursor_param: string;
  next_cursor_path: string | null;
  max_pages: number;
}

export interface FieldSpec {
  name: string;
  type: string;
  required: boolean;
  readonly: boolean;
  label: string | null;
  choices: string[] | null;
  relation: string | null;
}

/** The editable description of one REST resource, as the API reads and writes it. */
export interface ResourceConfig {
  name: string;
  label: string;
  list_endpoint: EndpointSpec | null;
  get_endpoint: EndpointSpec | null;
  create_endpoint: EndpointSpec | null;
  update_endpoint: EndpointSpec | null;
  items_path: string;
  item_path: string;
  id_field: string;
  pagination: PaginationConfig;
  filter_param_map: Record<string, string>;
  since_param: string | null;
  schema_fields: FieldSpec[];
}

export interface ResourceInput extends ResourceConfig {
  source: ResourceSource;
}

export interface StoredResource {
  profile_id: number;
  config: ResourceConfig;
  source: ResourceSource;
  updated_at: string;
}

/** A catalog entry the server could not read; it is skipped, not fatal. */
export interface ResourceProblem {
  name: string;
  reason: string;
}

export interface ResourceListing {
  items: StoredResource[];
  invalid: ResourceProblem[];
}

export interface PreviewRecord {
  id: string | null;
  fields: Record<string, unknown>;
}

export interface ResourceSchema {
  name: string;
  label: string;
  id_field: string;
  fields: FieldSpec[];
}

export interface PreviewResult {
  records: PreviewRecord[];
  schema: ResourceSchema;
}

export interface DiscoveredModel {
  name: string;
  label: string;
}

export interface ImportReport {
  candidates: ResourceConfig[];
  warnings: string[];
  base_path: string;
}

/** Exactly one of `url` or `document`. */
export type ImportRequest =
  { url: string; base_path?: string } | { document: string; base_path?: string };
