import type {
  EndpointSpec,
  FieldSpec,
  PaginationStrategy,
  ResourceConfig,
  ResourceInput,
  ResourceSource,
} from "@/features/resources/types";

export const STRATEGIES: readonly PaginationStrategy[] = ["none", "page", "offset", "cursor"];
export const CREATE_METHODS = ["POST", "PUT"] as const;
export const UPDATE_METHODS = ["PATCH", "PUT", "POST"] as const;

export interface ResourceFormState {
  profileId: string;
  name: string;
  label: string;
  list_path: string;
  get_path: string;
  create_path: string;
  create_method: string;
  update_path: string;
  update_method: string;
  id_field: string;
  items_path: string;
  item_path: string;
  since_param: string;
  /** One `field=parameter` pair per line. */
  filter_text: string;
  strategy: PaginationStrategy;
  page_param: string;
  size_param: string;
  first_page: string;
  total_pages_path: string;
  offset_param: string;
  limit_param: string;
  total_path: string;
  cursor_param: string;
  next_cursor_path: string;
  max_pages: string;
  /** Not editable here, but a PUT replaces the whole config, so they travel unchanged. */
  schema_fields: FieldSpec[];
  source: ResourceSource;
}

/** Form field -> translation key. */
export type FormErrors = Record<string, string>;

export const emptyForm = (profileId = ""): ResourceFormState => ({
  profileId,
  name: "",
  label: "",
  list_path: "",
  get_path: "",
  create_path: "",
  create_method: "POST",
  update_path: "",
  update_method: "PATCH",
  id_field: "id",
  items_path: "",
  item_path: "",
  since_param: "",
  filter_text: "",
  strategy: "none",
  page_param: "page",
  size_param: "page_size",
  first_page: "1",
  total_pages_path: "",
  offset_param: "offset",
  limit_param: "limit",
  total_path: "",
  cursor_param: "cursor",
  next_cursor_path: "",
  max_pages: "10000",
  schema_fields: [],
  source: "manual",
});

export function formFromConfig(
  config: ResourceConfig,
  source: ResourceSource,
  profileId: string,
): ResourceFormState {
  const pg = config.pagination;
  return {
    ...emptyForm(profileId),
    name: config.name,
    label: config.label,
    list_path: config.list_endpoint?.path ?? "",
    get_path: config.get_endpoint?.path ?? "",
    create_path: config.create_endpoint?.path ?? "",
    create_method: config.create_endpoint?.method ?? "POST",
    update_path: config.update_endpoint?.path ?? "",
    update_method: config.update_endpoint?.method ?? "PATCH",
    id_field: config.id_field,
    items_path: config.items_path,
    item_path: config.item_path,
    since_param: config.since_param ?? "",
    filter_text: Object.entries(config.filter_param_map)
      .map(([field, param]) => `${field}=${param}`)
      .join("\n"),
    strategy: pg.strategy,
    page_param: pg.page_param,
    size_param: pg.size_param,
    first_page: String(pg.first_page),
    total_pages_path: pg.total_pages_path ?? "",
    offset_param: pg.offset_param,
    limit_param: pg.limit_param,
    total_path: pg.total_path ?? "",
    cursor_param: pg.cursor_param,
    next_cursor_path: pg.next_cursor_path ?? "",
    max_pages: String(pg.max_pages),
    schema_fields: config.schema_fields,
    source,
  };
}

/** `field=param` per line; null when a non-empty line is malformed. */
export function parseFilterMap(text: string): Record<string, string> | null {
  const map: Record<string, string> = {};
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    const at = line.indexOf("=");
    const field = at < 0 ? "" : line.slice(0, at).trim();
    const param = at < 0 ? "" : line.slice(at + 1).trim();
    if (!field || !param) return null;
    map[field] = param;
  }
  return map;
}

const blank = (value: string): string | null => (value.trim() === "" ? null : value.trim());

function endpoint(method: string, path: string): EndpointSpec | null {
  const trimmed = path.trim();
  return trimmed ? { method, path: trimmed } : null;
}

/** Builds the API body. Call only on a form that passed `validateForm`. */
export function toInput(form: ResourceFormState): ResourceInput {
  return {
    name: form.name.trim(),
    label: form.label.trim(),
    list_endpoint: endpoint("GET", form.list_path),
    get_endpoint: endpoint("GET", form.get_path),
    create_endpoint: endpoint(form.create_method, form.create_path),
    update_endpoint: endpoint(form.update_method, form.update_path),
    items_path: form.items_path.trim(),
    item_path: form.item_path.trim(),
    id_field: form.id_field.trim(),
    pagination: {
      strategy: form.strategy,
      page_param: form.page_param.trim(),
      size_param: form.size_param.trim(),
      first_page: Number(form.first_page),
      total_pages_path: blank(form.total_pages_path),
      offset_param: form.offset_param.trim(),
      limit_param: form.limit_param.trim(),
      total_path: blank(form.total_path),
      cursor_param: form.cursor_param.trim(),
      next_cursor_path: blank(form.next_cursor_path),
      max_pages: Number(form.max_pages),
    },
    filter_param_map: parseFilterMap(form.filter_text) ?? {},
    since_param: blank(form.since_param),
    schema_fields: form.schema_fields,
    source: form.source,
  };
}

const SERVER_FIELDS: Record<string, string> = {
  list_endpoint: "list_path",
  get_endpoint: "get_path",
  create_endpoint: "create_path",
  update_endpoint: "update_path",
  pagination: "strategy",
  filter_param_map: "filter_text",
};

export const serverFieldToForm = (field: string): string => SERVER_FIELDS[field] ?? field;

const NAME = /^[A-Za-z0-9_.-]+$/;
const PLACEHOLDER = /\{([^{}]*)\}/g;
const REQUIRED = "resources.validation.required";

/** Mirrors `validate_resource_config` so most mistakes are caught before the request. */
function pathError(path: string, needsId: boolean): string | null {
  const trimmed = path.trim();
  if (!trimmed) return null;
  if (!trimmed.startsWith("/") || trimmed.startsWith("//") || /\s/.test(trimmed)) {
    return "resources.validation.path";
  }
  const names = [...trimmed.matchAll(PLACEHOLDER)].map((m) => m[1]);
  if (names.some((n) => n !== "id")) return "resources.validation.placeholder";
  if (/[{}]/.test(trimmed.replace(PLACEHOLDER, ""))) return "resources.validation.braces";
  const hasId = names.includes("id");
  if (needsId && !hasId) return "resources.validation.needsId";
  if (!needsId && hasId) return "resources.validation.noId";
  return null;
}

function integerError(value: string, min: number): string | null {
  return /^-?\d+$/.test(value.trim()) && Number(value) >= min
    ? null
    : "resources.validation.integer";
}

export function validateForm(
  form: ResourceFormState,
  existingNames: readonly string[],
): FormErrors {
  const errors: FormErrors = {};
  const require = (key: keyof ResourceFormState) => {
    if (!String(form[key]).trim()) errors[key] = REQUIRED;
  };

  if (!form.profileId) errors.profileId = REQUIRED;
  if (!form.name.trim()) errors.name = REQUIRED;
  else if (!NAME.test(form.name.trim())) errors.name = "resources.validation.name";
  else if (existingNames.includes(form.name.trim())) errors.name = "resources.errors.conflict";
  require("id_field");

  const paths = [
    ["list_path", form.list_path, false],
    ["get_path", form.get_path, true],
    ["create_path", form.create_path, false],
    ["update_path", form.update_path, true],
  ] as const;
  for (const [key, value, needsId] of paths) {
    const error = pathError(value, needsId);
    if (error) errors[key] = error;
  }
  if (!paths.some(([, value]) => value.trim())) {
    errors.list_path = "resources.validation.endpointNeeded";
  }

  if (parseFilterMap(form.filter_text) === null)
    errors.filter_text = "resources.validation.filters";

  if (form.strategy !== "none") {
    const maxPages = integerError(form.max_pages, 1);
    if (maxPages) errors.max_pages = maxPages;
    if (!form.list_path.trim() && !errors.list_path) {
      errors.list_path = "resources.validation.listNeeded";
    }
  }
  if (form.strategy === "page") {
    require("page_param");
    require("size_param");
    const first = integerError(form.first_page, 0);
    if (first) errors.first_page = first;
  } else if (form.strategy === "offset") {
    require("offset_param");
    require("limit_param");
  } else if (form.strategy === "cursor") {
    require("cursor_param");
    require("next_cursor_path");
  }
  return errors;
}
