import type {
  PaginationConfig,
  PreviewResult,
  ResourceConfig,
  StoredResource,
} from "@/features/resources/types";

/** Test fixtures shared by the resources suites (never imported by app code). */
export const noPagination: PaginationConfig = {
  strategy: "none",
  page_param: "page",
  size_param: "page_size",
  first_page: 1,
  total_pages_path: null,
  offset_param: "offset",
  limit_param: "limit",
  total_path: null,
  cursor_param: "cursor",
  next_cursor_path: null,
  max_pages: 10000,
};

export function configFixture(overrides: Partial<ResourceConfig> = {}): ResourceConfig {
  return {
    name: "clients",
    label: "Clientes",
    list_endpoint: { method: "GET", path: "/organization/clients" },
    get_endpoint: { method: "GET", path: "/organization/clients/{id}" },
    create_endpoint: null,
    update_endpoint: null,
    delete_endpoint: null,
    items_path: "items",
    item_path: "",
    id_field: "uuid",
    pagination: { ...noPagination, strategy: "page", total_pages_path: "total_pages" },
    filter_param_map: {},
    since_param: null,
    schema_fields: [],
    ...overrides,
  };
}

export function storedFixture(
  overrides: Omit<Partial<StoredResource>, "config"> & { config?: Partial<ResourceConfig> } = {},
): StoredResource {
  const { config, ...rest } = overrides;
  return {
    profile_id: 1,
    config: configFixture(config),
    source: "manual",
    updated_at: "2026-01-02T00:00:00Z",
    ...rest,
  };
}

export const previewFixture: PreviewResult = {
  records: [
    {
      id: "u-1",
      fields: { uuid: "u-1", name: "Acme", active: true, tags: ["a", "b"], note: null },
    },
    { id: "u-2", fields: { uuid: "u-2", name: "Globex", active: false, tags: [], note: "x" } },
  ],
  schema: {
    name: "clients",
    label: "Clientes",
    id_field: "uuid",
    fields: [
      {
        name: "uuid",
        type: "string",
        required: true,
        readonly: true,
        label: null,
        choices: null,
        relation: null,
      },
      {
        name: "name",
        type: "string",
        required: false,
        readonly: false,
        label: null,
        choices: null,
        relation: null,
      },
    ],
  },
};
