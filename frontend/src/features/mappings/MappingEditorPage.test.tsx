import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, Route, Routes } from "react-router-dom";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { MappingEditorPage } from "@/features/mappings/MappingEditorPage";
import { mappingDocFixture, storedMappingFixture } from "@/features/mappings/fixtures";
import type { MappingDoc } from "@/features/mappings/types";
import { storedFixture } from "@/features/resources/fixtures";
import type { PreviewResult } from "@/features/resources/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const field = (name: string, type: string, extra: Record<string, unknown> = {}) => ({
  name,
  type,
  required: false,
  readonly: false,
  label: null,
  choices: null,
  relation: null,
  ...extra,
});

const clients: PreviewResult = {
  records: [],
  schema: {
    name: "clients",
    label: "Clientes",
    id_field: "uuid",
    fields: [field("name", "string"), field("email", "string"), field("age", "string")],
  },
};
const partner: PreviewResult = {
  records: [],
  schema: {
    name: "res.partner",
    label: "Contact",
    id_field: "id",
    fields: [
      field("name", "string", { required: true }),
      field("email", "string"),
      field("phone", "string", { required: true }),
      field("age", "integer"),
    ],
  },
};

function routes(role: Role = "admin") {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    "GET /profiles/1/resources": () =>
      json({ items: [storedFixture({ config: { name: "clients" } })], invalid: [] }),
    "POST /profiles/1/resources/clients/preview?limit=1": () => json(clients),
    "POST /profiles/2/resources/res.partner/preview?limit=1": () => json(partner),
    "POST /profiles/2/discover": () => json({ items: [{ name: "res.partner", label: "Contact" }] }),
    "GET /mappings/clients-to-partner": () => json(storedMappingFixture({ version: 3 })),
  };
}

async function page(route: string, waitForEditor = true) {
  await renderApp(
    <>
      <Link to="/elsewhere">Fuera</Link>
      <Routes>
        <Route path="/mappings/new" element={<MappingEditorPage />} />
        <Route path="/mappings/:name/edit" element={<MappingEditorPage />} />
        <Route path="/mappings" element={<p>lista de mapeos</p>} />
        <Route path="/elsewhere" element={<p>otra página</p>} />
      </Routes>
    </>,
    route,
  );
  if (waitForEditor) await screen.findByLabelText("Nombre");
}

const side = (name: "Origen" | "Destino") => within(screen.getByRole("group", { name }));
const rule = (n: number) => within(screen.getByRole("group", { name: `Regla ${n}` }));

async function chooseSides() {
  await screen.findAllByRole("option", { name: "SUWE" });
  await userEvent.selectOptions(side("Origen").getByLabelText("Conexión"), "SUWE");
  await userEvent.selectOptions(await side("Origen").findByLabelText("Recurso"), "clients");
  await userEvent.selectOptions(side("Destino").getByLabelText("Conexión"), "Odoo producción");
  const model = await side("Destino").findByLabelText("Modelo de Odoo");
  await userEvent.clear(model);
  await userEvent.type(model, "res.partner");
  await userEvent.tab(); // the model is applied when the input loses focus
}

async function definition(): Promise<MappingDoc> {
  if (!screen.queryByRole("region", { name: "Definición (JSON)" })) {
    await userEvent.click(screen.getByRole("button", { name: "Ver JSON" }));
  }
  const region = screen.getByRole("region", { name: "Definición (JSON)" });
  return JSON.parse(region.textContent ?? "") as MappingDoc;
}

describe("MappingEditorPage: loading", () => {
  it("loads a saved mapping with its rules and locks the name", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    expect(await screen.findByLabelText("Nombre")).toHaveValue("clients-to-partner");
    expect(screen.getByLabelText("Nombre")).toHaveAttribute("readonly");
    expect(rule(1).getByLabelText("Campo de destino")).toHaveValue("name");
    expect(rule(2).getByLabelText("Campo de destino")).toHaveValue("email");
    expect(rule(2).getAllByRole("listitem")).toHaveLength(2);
    expect(await definition()).toEqual(mappingDocFixture());
  });

  it("reports a mapping that no longer exists", async () => {
    stubApi({
      ...routes(),
      "GET /mappings/clients-to-partner": () => json({ error: "not_found", detail: "x" }, 404),
    });
    await page("/mappings/clients-to-partner/edit", false);
    expect(await screen.findByText("El mapeo ya no existe.")).toBeInTheDocument();
  });

  it("shows operators a read-only view with no controls to change anything", async () => {
    stubApi(routes("operator"));
    await page("/mappings/clients-to-partner/edit", false);
    expect(await screen.findByRole("heading", { name: /clients-to-partner/ })).toBeInTheDocument();
    expect(screen.getByText("email")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Guardar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("sends operators away from the creation page", async () => {
    stubApi(routes("operator"));
    await page("/mappings/new", false);
    expect(await screen.findByText("lista de mapeos")).toBeInTheDocument();
  });
});

describe("MappingEditorPage: rules", () => {
  it("adds, reorders and removes rules with buttons", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await screen.findByLabelText("Nombre");
    await userEvent.click(screen.getByRole("button", { name: "Añadir regla" }));
    await userEvent.type(rule(3).getByLabelText("Campo de destino"), "phone");
    await userEvent.click(screen.getByRole("button", { name: "Subir regla 3" }));
    expect((await definition()).rules.map((r) => r.target)).toEqual(["name", "phone", "email"]);
    await userEvent.click(screen.getByRole("button", { name: "Bajar regla 1" }));
    expect((await definition()).rules.map((r) => r.target)).toEqual(["phone", "name", "email"]);
    await userEvent.click(screen.getByRole("button", { name: "Eliminar regla 1" }));
    expect((await definition()).rules.map((r) => r.target)).toEqual(["name", "email"]);
    expect(screen.getByRole("button", { name: "Subir regla 1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bajar regla 2" })).toBeDisabled();
  });

  it("edits a direct rule: source, default and required", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    const first = rule(1);
    await userEvent.clear(await first.findByLabelText("Campo de origen"));
    await userEvent.type(first.getByLabelText("Campo de origen"), "address.name");
    await userEvent.type(first.getByLabelText("Valor por defecto"), "sin nombre");
    await userEvent.click(first.getByLabelText("Obligatoria"));
    expect((await definition()).rules[0]).toEqual({
      target: "name",
      required: false,
      expr: { type: "direct", source: "address.name", default: "sin nombre" },
    });
  });

  it("switches a rule to a constant and types the value", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await userEvent.selectOptions(await rule(1).findByLabelText("Tipo de expresión"), "Valor fijo");
    await userEvent.type(rule(1).getByLabelText("Valor"), "42");
    expect((await definition()).rules[0]?.expr).toEqual({ type: "constant", value: 42 });
  });

  it("builds a concat with ordered parts and a separator", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await userEvent.selectOptions(await rule(1).findByLabelText("Tipo de expresión"), "Concatenar");
    await userEvent.click(rule(1).getByRole("button", { name: "Añadir parte" }));
    await userEvent.click(rule(1).getByRole("button", { name: "Añadir parte" }));
    await userEvent.type(rule(1).getByLabelText("Parte 1 · Campo de origen"), "first");
    await userEvent.type(rule(1).getByLabelText("Parte 2 · Campo de origen"), "last");
    await userEvent.type(rule(1).getByLabelText("Separador"), " ");
    await userEvent.click(rule(1).getByRole("button", { name: "Subir parte 2" }));
    expect((await definition()).rules[0]?.expr).toEqual({
      type: "concat",
      parts: [
        { type: "direct", source: "last", default: null },
        { type: "direct", source: "first", default: null },
      ],
      separator: " ",
      skip_empty: true,
    });
  });

  it("edits the step chain of a transform: add, reorder, remove", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    const second = rule(2);
    await userEvent.click(await second.findByRole("button", { name: "Eliminar paso 1" }));
    await userEvent.selectOptions(second.getByLabelText("Tipo de paso"), "Mayúsculas");
    await userEvent.click(second.getByRole("button", { name: "Añadir paso" }));
    await userEvent.selectOptions(second.getByLabelText("Tipo de paso"), "Recortar espacios");
    await userEvent.click(second.getByRole("button", { name: "Añadir paso" }));
    await userEvent.click(second.getByRole("button", { name: "Subir paso 3" }));
    const expr = (await definition()).rules[1]?.expr;
    expect(expr).toMatchObject({
      type: "transform",
      steps: [{ type: "lower" }, { type: "trim" }, { type: "upper" }],
    });
    expect(second.getByRole("button", { name: "Subir paso 1" })).toBeDisabled();
  });

  it("configures the parametrised steps", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    const second = rule(2);
    for (const label of [
      "Formato de fecha",
      "A céntimos",
      "Reemplazar",
      "Subcadena",
      "Primer valor no vacío",
    ]) {
      await userEvent.selectOptions(await second.findByLabelText("Tipo de paso"), label);
      await userEvent.click(second.getByRole("button", { name: "Añadir paso" }));
    }
    await userEvent.clear(second.getByLabelText("Formato de entrada"));
    await userEvent.type(second.getByLabelText("Formato de entrada"), "%d/%m/%Y");
    await userEvent.clear(second.getByLabelText("Factor"));
    await userEvent.type(second.getByLabelText("Factor"), "1000");
    await userEvent.type(second.getByLabelText("Texto a buscar"), "-");
    await userEvent.type(second.getByLabelText("Reemplazar por"), "_");
    await userEvent.clear(second.getByLabelText("Inicio"));
    await userEvent.type(second.getByLabelText("Inicio"), "2");
    await userEvent.type(second.getByLabelText("Fin (opcional)"), "6");
    await userEvent.click(second.getByRole("button", { name: "Añadir alternativa" }));
    await userEvent.type(second.getByLabelText("Alternativa 1 · Campo de origen"), "alt");
    const steps = ((await definition()).rules[1]?.expr as { steps: unknown[] }).steps.slice(2);
    expect(steps).toEqual([
      { type: "date_format", in_format: "%d/%m/%Y", out_format: "iso" },
      { type: "to_cents", factor: 1000 },
      { type: "replace", old: "-", new: "_" },
      { type: "substring", start: 2, end: 6 },
      { type: "coalesce", alternatives: [{ type: "direct", source: "alt", default: null }] },
    ]);
  });

  it("edits a lookup table and its missing-value policy", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    const second = rule(2);
    await userEvent.selectOptions(
      await second.findByLabelText("Tipo de paso"),
      "Tabla de equivalencias",
    );
    await userEvent.click(second.getByRole("button", { name: "Añadir paso" }));
    await userEvent.click(second.getByRole("button", { name: "Añadir equivalencia" }));
    await userEvent.type(second.getByLabelText("Valor de origen 1"), "ES");
    await userEvent.type(second.getByLabelText("Valor de destino 1"), "Spain");
    await userEvent.click(second.getByRole("button", { name: "Añadir equivalencia" }));
    await userEvent.type(second.getByLabelText("Valor de origen 2"), "FR");
    await userEvent.type(second.getByLabelText("Valor de destino 2"), "33");
    expect(second.queryByLabelText("Valor por defecto")).toBeNull();
    await userEvent.selectOptions(
      second.getByLabelText("Si no hay equivalencia"),
      "Usar valor por defecto",
    );
    await userEvent.type(second.getByLabelText("Valor por defecto"), "other");
    await userEvent.click(second.getByRole("button", { name: "Eliminar equivalencia 2" }));
    await userEvent.click(second.getByRole("button", { name: "Añadir equivalencia" }));
    await userEvent.type(second.getByLabelText("Valor de origen 2"), "PT");
    await userEvent.type(second.getByLabelText("Valor de destino 2"), "Portugal");
    const steps = ((await definition()).rules[1]?.expr as { steps: unknown[] }).steps;
    expect(steps[2]).toEqual({
      type: "lookup",
      table: { ES: "Spain", PT: "Portugal" },
      on_missing: "default",
      default: "other",
    });
  });
});

describe("MappingEditorPage: schemas and hints", () => {
  it("loads both schemas, warns about unmapped required fields and type mismatches", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await chooseSides();
    expect(
      await screen.findByText(/Falta una regla para el campo obligatorio «phone»/),
    ).toBeInTheDocument();
    // age (string) mapped to an integer target
    await userEvent.click(screen.getByRole("button", { name: "Añadir regla" }));
    await userEvent.type(rule(3).getByLabelText("Campo de destino"), "age");
    await userEvent.type(rule(3).getByLabelText("Campo de origen"), "age");
    expect(
      await rule(3).findByText(/produce string pero «integer»|string.*integer/),
    ).toBeInTheDocument();
    expect(side("Origen").getByRole("table", { name: "Campos de origen" })).toBeInTheDocument();
    expect(side("Destino").getByText("phone")).toBeInTheDocument();
  });

  it("flags a duplicated target and blocks saving", async () => {
    const mock = stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await screen.findByLabelText("Nombre");
    await userEvent.click(screen.getByRole("button", { name: "Añadir regla" }));
    await userEvent.type(rule(3).getByLabelText("Campo de destino"), "name");
    expect(await rule(3).findByText(/ya tiene una regla/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Guardar nueva versión" })).toBeDisabled();
    expect(mock).not.toHaveBeenCalledWith(
      expect.stringContaining("/mappings/clients"),
      expect.objectContaining({ method: "PUT" }),
    );
  });
});

describe("MappingEditorPage: suggestions", () => {
  it("pre-fills rules for review without saving anything", async () => {
    const mock = stubApi({
      ...routes(),
      "POST /mappings/suggest": () =>
        json({
          definition: mappingDocFixture({
            rules: [
              {
                target: "phone",
                required: false,
                expr: { type: "direct", source: "tel", default: null },
              },
              {
                target: "name",
                required: false,
                expr: { type: "direct", source: "x", default: null },
              },
            ],
          }),
          unmatched_source: ["age"],
          unmatched_target: ["id"],
        }),
    });
    await page("/mappings/clients-to-partner/edit");
    await chooseSides();
    await userEvent.click(await screen.findByRole("button", { name: "Sugerir mapeo" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Se ha añadido 1 regla sugerida");
    expect(screen.getByRole("status")).toHaveTextContent("age");
    const doc = await definition();
    expect(doc.rules.map((r) => r.target)).toEqual(["name", "email", "phone"]);
    expect(doc.rules[0]?.expr).toMatchObject({ source: "name" });
    expect(mock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("needs both sides before it can suggest", async () => {
    stubApi(routes());
    await page("/mappings/new");
    expect(await screen.findByRole("button", { name: "Sugerir mapeo" })).toBeDisabled();
  });
});

describe("MappingEditorPage: saving", () => {
  it("creates a mapping, sends the chosen profiles and reports the new version", async () => {
    const mock = stubApi({
      ...routes(),
      "PUT /mappings/new-one": () =>
        json({
          mapping: storedMappingFixture({ name: "new-one", version: 1 }),
          created: true,
          warnings: [],
        }),
    });
    await page("/mappings/new");
    await userEvent.type(await screen.findByLabelText("Nombre"), "new-one");
    await chooseSides();
    await userEvent.click(screen.getByRole("button", { name: "Añadir regla" }));
    await userEvent.type(rule(1).getByLabelText("Campo de destino"), "name");
    await userEvent.type(rule(1).getByLabelText("Campo de origen"), "name");
    await userEvent.click(screen.getByRole("button", { name: "Guardar nueva versión" }));
    expect(await screen.findByText("Versión 1 guardada.")).toBeInTheDocument();
    const call = mock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(call[1]!.body))).toEqual({
      definition: {
        schema_version: 1,
        name: "new-one",
        source_resource: "clients",
        target_resource: "res.partner",
        rules: [
          {
            target: "name",
            required: false,
            expr: { type: "direct", source: "name", default: null },
          },
        ],
      },
      source_profile_id: 1,
      target_profile_id: 2,
    });
    // saved: leaving no longer asks for confirmation, and the name is locked
    expect(screen.getByLabelText("Nombre")).toHaveAttribute("readonly");
    await userEvent.click(screen.getByRole("link", { name: "Fuera" }));
    expect(await screen.findByText("otra página")).toBeInTheDocument();
  });

  it("says when nothing changed", async () => {
    stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json({ mapping: storedMappingFixture({ version: 3 }), created: false, warnings: [] }),
    });
    await page("/mappings/clients-to-partner/edit");
    await userEvent.click(await screen.findByRole("button", { name: "Guardar nueva versión" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "la versión 3 ya contiene esta definición",
    );
  });

  it("shows server issues on the offending rule and the rest in a summary", async () => {
    stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json(
          {
            error: "validation_error",
            detail: "x",
            issues: [
              { path: "rules[1].expr.steps[0]", severity: "error", message: "unknown step" },
              {
                path: "target.phone",
                severity: "error",
                message: "required target field 'phone' has no rule",
              },
            ],
          },
          422,
        ),
    });
    await page("/mappings/clients-to-partner/edit");
    await userEvent.click(await screen.findByRole("button", { name: "Guardar nueva versión" }));
    expect(await rule(2).findByText(/unknown step/)).toBeInTheDocument();
    expect(rule(1).queryByText(/unknown step/)).not.toBeInTheDocument();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("El mapeo no es válido");
    expect(alert).toHaveTextContent("required target field 'phone' has no rule");
  });

  it("shows the retry delay on 429", async () => {
    stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json({ error: "too_many_requests", detail: "" }, 429, { "Retry-After": "12" }),
    });
    await page("/mappings/clients-to-partner/edit");
    await userEvent.click(await screen.findByRole("button", { name: "Guardar nueva versión" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("12 segundos");
  });
});

describe("MappingEditorPage: unsaved changes", () => {
  it("asks before leaving with unsaved edits and lets the author stay", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await userEvent.click(await screen.findByRole("button", { name: "Añadir regla" }));
    await userEvent.click(screen.getByRole("link", { name: "Fuera" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Cambios sin guardar");
    await userEvent.click(within(dialog).getByRole("button", { name: "Seguir editando" }));
    expect(screen.queryByText("otra página")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("link", { name: "Fuera" }));
    await userEvent.click(await screen.findByRole("button", { name: "Salir sin guardar" }));
    expect(await screen.findByText("otra página")).toBeInTheDocument();
  });

  it("does not ask when nothing changed", async () => {
    stubApi(routes());
    await page("/mappings/clients-to-partner/edit");
    await screen.findByLabelText("Nombre");
    await userEvent.click(screen.getByRole("link", { name: "Fuera" }));
    expect(await screen.findByText("otra página")).toBeInTheDocument();
  });
});
