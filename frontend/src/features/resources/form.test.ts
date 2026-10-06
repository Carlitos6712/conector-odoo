import { configFixture, noPagination } from "@/features/resources/fixtures";
import {
  emptyForm,
  formFromConfig,
  parseFilterMap,
  serverFieldToForm,
  toInput,
  validateForm,
  type ResourceFormState,
} from "@/features/resources/form";

const valid = (patch: Partial<ResourceFormState> = {}): ResourceFormState => ({
  ...emptyForm("1"),
  name: "clients",
  list_path: "/clients",
  ...patch,
});

describe("resource form <-> config", () => {
  it("round-trips a config without losing hidden parts", () => {
    const config = configFixture({
      filter_param_map: { status: "state" },
      since_param: "updated_since",
      schema_fields: [
        {
          name: "uuid",
          type: "string",
          required: true,
          readonly: true,
          label: null,
          choices: null,
          relation: null,
        },
      ],
    });
    const form = formFromConfig(config, "openapi", "1");
    expect(toInput(form)).toEqual({ ...config, source: "openapi" });
  });

  it("turns blank paths into missing endpoints and blank optionals into null", () => {
    const input = toInput(
      valid({ get_path: "", create_path: "  ", total_pages_path: "", since_param: " " }),
    );
    expect(input.get_endpoint).toBeNull();
    expect(input.create_endpoint).toBeNull();
    expect(input.list_endpoint).toEqual({ method: "GET", path: "/clients" });
    expect(input.pagination.total_pages_path).toBeNull();
    expect(input.since_param).toBeNull();
    expect(input.label).toBe("");
  });

  it("keeps the chosen write methods", () => {
    const input = toInput(
      valid({ create_path: "/clients", create_method: "PUT", update_path: "/clients/{id}" }),
    );
    expect(input.create_endpoint).toEqual({ method: "PUT", path: "/clients" });
    expect(input.update_endpoint).toEqual({ method: "PATCH", path: "/clients/{id}" });
  });

  it("keeps the delete endpoint (always DELETE) through the form", () => {
    const config = configFixture({ delete_endpoint: { method: "DELETE", path: "/clients/{id}" } });
    const form = formFromConfig(config, "manual", "1");
    expect(form.delete_path).toBe("/clients/{id}");
    expect(toInput(form).delete_endpoint).toEqual({ method: "DELETE", path: "/clients/{id}" });
    expect(toInput(valid({ delete_path: " " })).delete_endpoint).toBeNull();
    expect(serverFieldToForm("delete_endpoint")).toBe("delete_path");
    expect(validateForm(valid({ delete_path: "/c" }), []).delete_path).toBe(
      "resources.validation.needsId",
    );
  });

  it("parses filter lines", () => {
    expect(parseFilterMap("status=state\n\n email = mail ")).toEqual({
      status: "state",
      email: "mail",
    });
    expect(parseFilterMap("broken")).toBeNull();
    expect(parseFilterMap("=x")).toBeNull();
  });

  it("maps server field names to form fields", () => {
    expect(serverFieldToForm("list_endpoint")).toBe("list_path");
    expect(serverFieldToForm("pagination")).toBe("strategy");
    expect(serverFieldToForm("id_field")).toBe("id_field");
  });
});

describe("validateForm", () => {
  it("accepts a minimal valid form", () => {
    expect(validateForm(valid(), [])).toEqual({});
  });

  it("requires a profile, a safe name and an id field", () => {
    const errors = validateForm(valid({ profileId: "", name: "bad name", id_field: " " }), []);
    expect(Object.keys(errors).sort()).toEqual(["id_field", "name", "profileId"]);
  });

  it("rejects a name already present in the connection", () => {
    expect(validateForm(valid(), ["clients"]).name).toBe("resources.errors.conflict");
  });

  it("needs at least one endpoint", () => {
    expect(validateForm(valid({ list_path: "" }), []).list_path).toBe(
      "resources.validation.endpointNeeded",
    );
  });

  it("mirrors the endpoint path rules of the API", () => {
    expect(validateForm(valid({ list_path: "clients" }), []).list_path).toBe(
      "resources.validation.path",
    );
    expect(validateForm(valid({ list_path: "//x" }), []).list_path).toBe(
      "resources.validation.path",
    );
    expect(validateForm(valid({ list_path: "/a b" }), []).list_path).toBe(
      "resources.validation.path",
    );
    expect(validateForm(valid({ list_path: "/c/{id}" }), []).list_path).toBe(
      "resources.validation.noId",
    );
    expect(validateForm(valid({ get_path: "/c" }), []).get_path).toBe(
      "resources.validation.needsId",
    );
    expect(validateForm(valid({ update_path: "/c/{other}" }), []).update_path).toBe(
      "resources.validation.placeholder",
    );
  });

  it("requires the parameters of the chosen pagination strategy only", () => {
    const base = { list_path: "/c" };
    expect(validateForm(valid({ ...base, strategy: "page", page_param: "" }), [])).toHaveProperty(
      "page_param",
    );
    expect(
      validateForm(valid({ ...base, strategy: "offset", offset_param: "", page_param: "" }), []),
    ).toEqual({ offset_param: "resources.validation.required" });
    const cursor = validateForm(valid({ ...base, strategy: "cursor", next_cursor_path: "" }), []);
    expect(cursor).toEqual({ next_cursor_path: "resources.validation.required" });
    expect(validateForm(valid({ ...base, strategy: "none", page_param: "" }), [])).toEqual({});
  });

  it("validates numbers and the filter map", () => {
    expect(validateForm(valid({ strategy: "page", first_page: "-1" }), [])).toHaveProperty(
      "first_page",
    );
    expect(validateForm(valid({ strategy: "page", first_page: "x" }), [])).toHaveProperty(
      "first_page",
    );
    expect(validateForm(valid({ strategy: "page", max_pages: "0" }), [])).toHaveProperty(
      "max_pages",
    );
    expect(validateForm(valid({ filter_text: "nope" }), [])).toHaveProperty("filter_text");
  });

  it("does not need a list endpoint to leave pagination off", () => {
    expect(validateForm(valid({ list_path: "", get_path: "/c/{id}" }), [])).toEqual({});
    expect(noPagination.strategy).toBe("none");
  });
});
