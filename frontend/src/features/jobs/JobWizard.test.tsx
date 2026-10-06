import { fireEvent, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import { JobWizardPage } from "@/features/jobs/JobWizardPage";
import { mappingDocFixture, storedMappingFixture } from "@/features/mappings/fixtures";
import { storedFixture } from "@/features/resources/fixtures";
import type { PreviewResult } from "@/features/resources/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const field = (name: string, type = "string") => ({
  name,
  type,
  required: false,
  readonly: false,
  label: null,
  choices: null,
  relation: null,
});
const preview = (name: string, fields: string[]): PreviewResult => ({
  records: [],
  schema: { name, label: name, id_field: "id", fields: fields.map((f) => field(f)) },
});

const forward = storedMappingFixture();
const reverse = storedMappingFixture({
  name: "partner-to-clients",
  definition: mappingDocFixture({
    name: "partner-to-clients",
    source_resource: "res.partner",
    target_resource: "clients",
  }),
});
const unrelated = storedMappingFixture({
  name: "orders-to-sales",
  definition: mappingDocFixture({
    name: "orders-to-sales",
    source_resource: "orders",
    target_resource: "sale.order",
  }),
});

function routes(role: Role = "admin") {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    "GET /mappings": () => json({ items: [forward, reverse, unrelated] }),
    "GET /mappings/clients-to-partner/versions": () =>
      json({ items: [{ ...forward, version: 2 }, forward] }),
    "GET /mappings/partner-to-clients/versions": () => json({ items: [reverse] }),
    "GET /profiles/1/resources": () =>
      json({
        items: [
          storedFixture({ config: { name: "clients" } }),
          storedFixture({ config: { name: "orders" } }),
        ],
        invalid: [],
      }),
    "POST /profiles/1/resources/clients/preview?limit=1": () =>
      json(preview("clients", ["name", "email", "updated_at"])),
    "POST /profiles/1/resources/orders/preview?limit=1": () => json(preview("orders", ["total"])),
    "POST /profiles/2/resources/res.partner/preview?limit=1": () =>
      json(preview("res.partner", ["name", "email", "write_date"])),
    "POST /profiles/2/resources/sale.order/preview?limit=1": () =>
      json(preview("sale.order", ["amount_total"])),
    "POST /profiles/2/discover": () => json({ items: [{ name: "res.partner", label: "Contact" }] }),
  };
}

async function page(route = "/jobs/new", waitForForm = true) {
  await renderApp(
    <Routes>
      <Route path="/jobs/new" element={<JobWizardPage />} />
      <Route path="/jobs/:id/edit" element={<JobWizardPage />} />
      <Route path="/jobs" element={<p>lista de tareas</p>} />
    </Routes>,
    route,
  );
  if (waitForForm) await screen.findByLabelText("Nombre");
}

const side = (name: "Origen" | "Destino") => within(screen.getByRole("group", { name }));
const next = () => userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
const back = () => userEvent.click(screen.getByRole("button", { name: "Anterior" }));
const currentStep = () => screen.getByRole("listitem", { current: "step" });

async function fillBasics(name = "Clientes a Odoo", direction?: string) {
  await userEvent.type(await screen.findByLabelText("Nombre"), name);
  if (direction) await userEvent.click(screen.getByRole("radio", { name: direction }));
  await next();
}

async function chooseSides(resource = "clients", model = "res.partner") {
  await screen.findAllByRole("option", { name: "SUWE" });
  await userEvent.selectOptions(side("Origen").getByLabelText("Conexión"), "SUWE");
  await userEvent.selectOptions(await side("Origen").findByLabelText("Recurso"), resource);
  await userEvent.selectOptions(side("Destino").getByLabelText("Conexión"), "Odoo producción");
  const input = await side("Destino").findByLabelText("Modelo de Odoo");
  await userEvent.clear(input);
  await userEvent.type(input, model);
  await userEvent.tab(); // the model is applied when the input loses focus
}

const bodyOf = (mock: ReturnType<typeof stubApi>, method: string, url: string) => {
  const call = mock.mock.calls.find(
    ([u, init]) => u === url && (init as RequestInit | undefined)?.method === method,
  );
  return call ? JSON.parse(String((call[1] as RequestInit).body)) : undefined;
};

/** Steps 1 and 2 of a plain one way job. */
async function reachOptions() {
  await fillBasics();
  await chooseSides();
  await userEvent.selectOptions(await screen.findByLabelText("Mapeo"), "clients-to-partner");
  await next();
}

const expectedBase = {
  name: "Clientes a Odoo",
  source: { profile_id: 1, resource: "clients" },
  target: { profile_id: 2, resource: "res.partner" },
  mapping: { name: "clients-to-partner", version: null },
  reverse_mapping: null,
  direction: "a_to_b",
  trigger: { kind: "manual" },
  record_filter: { equals: {}, since: null, raw: null },
  reverse_record_filter: { equals: {}, since: null, raw: null },
  batch_size: 100,
  upsert_key: "xref",
  conflict_rule: "source_wins",
  source_updated_field: null,
  target_updated_field: null,
  enabled: true,
};

describe("JobWizard", () => {
  it("creates a manual one way job through the five steps", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Nueva tarea");
    await reachOptions();
    await next(); // options keep their defaults
    await next(); // manual trigger
    expect(currentStep()).toHaveTextContent("Revisión");
    expect(screen.getByText("clients-to-partner")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    expect(await screen.findByText("lista de tareas")).toBeInTheDocument();
    expect(bodyOf(mock, "POST", "/admin/api/jobs")).toEqual(expectedBase);
  });

  it("does not move on until the step is valid", async () => {
    stubApi(routes());
    await page();
    await next();
    expect(await screen.findByText("Escribe un nombre.")).toBeInTheDocument();
    expect(currentStep()).toHaveTextContent("Datos básicos");
    await userEvent.type(screen.getByLabelText("Nombre"), "Tarea");
    await next();
    await next();
    expect((await screen.findAllByText("Obligatorio.")).length).toBeGreaterThan(0);
    expect(currentStep()).toHaveTextContent("Origen y destino");
  });

  it("goes back keeping what was entered", async () => {
    stubApi(routes());
    await page();
    await fillBasics("Mi tarea");
    await back();
    expect(screen.getByLabelText("Nombre")).toHaveValue("Mi tarea");
  });

  it("offers only the mappings that fit the chosen resources", async () => {
    stubApi(routes());
    await page();
    await fillBasics();
    await chooseSides();
    const select = await screen.findByLabelText("Mapeo");
    expect(within(select).getByRole("option", { name: "clients-to-partner" })).toBeInTheDocument();
    expect(
      within(select).queryByRole("option", { name: "orders-to-sales" }),
    ).not.toBeInTheDocument();
    expect(
      within(select).queryByRole("option", { name: "partner-to-clients" }),
    ).not.toBeInTheDocument();
  });

  it("says when no mapping connects the two resources and links to the editor", async () => {
    stubApi(routes());
    await page();
    await fillBasics();
    await chooseSides("clients", "sale.order");
    expect(
      await screen.findByText(/Ningún mapeo convierte clients en sale\.order/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Crear un mapeo" })).toHaveAttribute(
      "href",
      "/mappings/new",
    );
  });

  it("refuses a chosen mapping that no longer fits after the resources changed", async () => {
    stubApi(routes());
    await page();
    await fillBasics();
    await chooseSides();
    await userEvent.selectOptions(await screen.findByLabelText("Mapeo"), "clients-to-partner");
    await userEvent.selectOptions(side("Origen").getByLabelText("Recurso"), "orders");
    await next();
    expect(
      await screen.findByText("El mapeo no encaja con los recursos elegidos."),
    ).toBeInTheDocument();
    expect(currentStep()).toHaveTextContent("Origen y destino");
  });

  it("pins a mapping version when asked", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await fillBasics();
    await chooseSides();
    await userEvent.selectOptions(await screen.findByLabelText("Mapeo"), "clients-to-partner");
    await screen.findByRole("option", { name: "v2" });
    await userEvent.selectOptions(screen.getByLabelText("Versión del mapeo"), "v2");
    await next();
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs").mapping).toEqual({
      name: "clients-to-partner",
      version: 2,
    });
  });

  it("asks for a reverse mapping and the conflict rule on a bidirectional job", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await fillBasics("Sincro doble", "Bidireccional");
    await chooseSides();
    await userEvent.selectOptions(await screen.findByLabelText("Mapeo"), "clients-to-partner");
    await next();
    expect(await screen.findByText("Obligatorio.")).toBeInTheDocument();
    const reverseSelect = screen.getByLabelText("Mapeo inverso");
    expect(
      within(reverseSelect).getByRole("option", { name: "partner-to-clients" }),
    ).toBeInTheDocument();
    expect(
      within(reverseSelect).queryByRole("option", { name: "clients-to-partner" }),
    ).not.toBeInTheDocument();
    await userEvent.selectOptions(reverseSelect, "partner-to-clients");
    await next();

    await userEvent.selectOptions(
      screen.getByLabelText("Regla de conflicto"),
      "Gana el más reciente",
    );
    await next();
    expect(screen.getAllByText("Obligatorio.")).toHaveLength(2);
    await userEvent.type(
      screen.getByLabelText("Campo de fecha de modificación del origen"),
      "updated_at",
    );
    await userEvent.type(
      screen.getByLabelText("Campo de fecha de modificación del destino"),
      "write_date",
    );
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs")).toMatchObject({
      direction: "bidirectional",
      reverse_mapping: { name: "partner-to-clients", version: null },
      conflict_rule: "newest_wins",
      source_updated_field: "updated_at",
      target_updated_field: "write_date",
    });
  });

  it("hides the conflict options on a one way job", async () => {
    stubApi(routes());
    await page();
    await reachOptions();
    expect(screen.queryByLabelText("Regla de conflicto")).not.toBeInTheDocument();
  });

  it("builds a field upsert key and record filters", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await reachOptions();
    await userEvent.click(screen.getByRole("radio", { name: "Buscar por un campo del destino" }));
    await userEvent.type(screen.getByLabelText("Campo del destino"), "email");
    await userEvent.click(screen.getByRole("button", { name: "Añadir filtro" }));
    await userEvent.type(screen.getByLabelText("Campo del filtro 1"), "active");
    await userEvent.type(screen.getByLabelText("Valor del filtro 1"), "true");
    fireEvent.change(screen.getByLabelText("Tamaño de lote"), { target: { value: "250" } });
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs")).toMatchObject({
      upsert_key: "field:email",
      record_filter: { equals: { active: true }, since: null, raw: null },
      reverse_record_filter: { equals: {}, since: null, raw: null },
      batch_size: 250,
    });
  });

  it("suggests the fields of the target while filling the options", async () => {
    stubApi(routes());
    await page();
    await reachOptions();
    await userEvent.click(screen.getByRole("radio", { name: "Buscar por un campo del destino" }));
    const input = screen.getByLabelText("Campo del destino");
    const list = document.getElementById(input.getAttribute("list")!)!;
    await vi.waitFor(() => {
      const values = [...list.querySelectorAll("option")].map((o) => o.getAttribute("value"));
      expect(values).toEqual(expect.arrayContaining(["email", "write_date"]));
    });
  });

  it("validates the batch size, the upsert field and the filter rows", async () => {
    stubApi(routes());
    await page();
    await reachOptions();
    fireEvent.change(screen.getByLabelText("Tamaño de lote"), { target: { value: "0" } });
    await userEvent.click(screen.getByRole("radio", { name: "Buscar por un campo del destino" }));
    await userEvent.click(screen.getByRole("button", { name: "Añadir filtro" }));
    await userEvent.type(screen.getByLabelText("Valor del filtro 1"), "x");
    await next();
    expect(await screen.findByText("Indica un número entero entre 1 y 1000.")).toBeInTheDocument();
    expect(screen.getByText("Indica el campo del filtro.")).toBeInTheDocument();
    expect(screen.getByText("Obligatorio.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Quitar filtro 1" }));
    expect(screen.queryByLabelText("Campo del filtro 1")).not.toBeInTheDocument();
  });

  it("saves a schedule built from a preset", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await reachOptions();
    await next();
    await userEvent.click(screen.getByRole("radio", { name: "Programado" }));
    expect(screen.getByText("Todos los días a las 02:00 UTC")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Hora"), { target: { value: "6" } });
    expect(screen.getByText("Todos los días a las 06:00 UTC")).toBeInTheDocument();
    await next();
    expect(screen.getByText("Todos los días a las 06:00 UTC")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs").trigger).toEqual({
      kind: "schedule",
      cron: "0 6 * * *",
    });
  });

  it("does not leave the trigger step with an invalid cron expression", async () => {
    stubApi(routes());
    await page();
    await reachOptions();
    await next();
    await userEvent.click(screen.getByRole("radio", { name: "Programado" }));
    await userEvent.click(screen.getByRole("radio", { name: "Avanzado" }));
    fireEvent.change(screen.getByLabelText("Expresión cron"), { target: { value: "61 * * * *" } });
    await next();
    expect(currentStep()).toHaveTextContent("Disparador");
    expect(screen.getByRole("alert")).toHaveTextContent("Valor fuera de rango.");
  });

  it("saves a webhook trigger with several events", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await reachOptions();
    await next();
    await userEvent.click(screen.getByRole("radio", { name: "Webhook" }));
    await next();
    expect(await screen.findByText("Elige al menos un evento.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("checkbox", { name: "sale_order.confirmed" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "partner.created" }));
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs").trigger).toEqual({
      kind: "webhook",
      event_types: ["partner.created", "sale_order.confirmed"],
    });
  });

  it("creates the job disabled when asked", async () => {
    const mock = stubApi({ ...routes(), "POST /jobs": () => json(jobFixture(), 201) });
    await page();
    await reachOptions();
    await next();
    await next();
    await userEvent.click(screen.getByRole("checkbox", { name: "Activar la tarea al guardar" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    expect(bodyOf(mock, "POST", "/admin/api/jobs").enabled).toBe(false);
  });

  it("points a mapping mismatch from the server at the mapping field", async () => {
    stubApi({
      ...routes(),
      "POST /jobs": () =>
        json(
          {
            error: "validation_error",
            detail:
              "mapping 'clients-to-partner' maps 'a' to 'b', but the job syncs 'clients' to 'res.partner'",
          },
          422,
        ),
    });
    await page();
    await reachOptions();
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    expect(await screen.findByLabelText("Mapeo")).toBeInvalid();
    expect(currentStep()).toHaveTextContent("Origen y destino");
    expect(
      screen.getAllByText("El mapeo no encaja con los recursos elegidos.").length,
    ).toBeGreaterThan(0);
  });

  it("returns to the name when it is already taken", async () => {
    stubApi({
      ...routes(),
      "POST /jobs": () => json({ error: "conflict", detail: "name taken" }, 409),
    });
    await page();
    await reachOptions();
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    expect(await screen.findByText("Ya existe una tarea con ese nombre.")).toBeInTheDocument();
    expect(currentStep()).toHaveTextContent("Datos básicos");
  });

  it("explains a rate limited save", async () => {
    stubApi({
      ...routes(),
      "POST /jobs": () =>
        json({ error: "too_many_requests", detail: "" }, 429, { "Retry-After": "4" }),
    });
    await page();
    await reachOptions();
    await next();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/4 segundos/);
  });

  it("edits an existing job and saves it with PUT", async () => {
    const stored = jobFixture({
      trigger: { kind: "schedule", cron: "30 9 * * 1,3" },
      mapping: { name: "clients-to-partner", version: 2 },
    });
    const mock = stubApi({
      ...routes(),
      "GET /jobs/7": () => json(stored),
      "PUT /jobs/7": () => json(stored),
    });
    await page("/jobs/7/edit");
    expect(screen.getByLabelText("Nombre")).toHaveValue("Clientes a Odoo");
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Editar tarea");
    await userEvent.clear(screen.getByLabelText("Nombre"));
    await userEvent.type(screen.getByLabelText("Nombre"), "Renombrada");
    await next();
    expect(await side("Origen").findByLabelText("Recurso")).toHaveValue("clients");
    await next();
    await next();
    expect(screen.getByLabelText("Hora")).toHaveValue(9);
    expect(screen.getByRole("checkbox", { name: "Mié" })).toBeChecked();
    await next();
    await userEvent.click(screen.getByRole("button", { name: "Guardar tarea" }));
    await screen.findByText("lista de tareas");
    const sent = bodyOf(mock, "PUT", "/admin/api/jobs/7");
    expect(sent).toMatchObject({
      name: "Renombrada",
      mapping: { name: "clients-to-partner", version: 2 },
      trigger: { kind: "schedule", cron: "30 9 * * 1,3" },
    });
    expect(sent).not.toHaveProperty("id");
  });

  it("reports a job that does not exist", async () => {
    stubApi({
      ...routes(),
      "GET /jobs/9": () => json({ error: "not_found", detail: "sync job 9 not found" }, 404),
    });
    await page("/jobs/9/edit", false);
    expect(await screen.findByRole("alert")).toHaveTextContent("La tarea ya no existe.");
  });

  it("sends operators back to the list", async () => {
    stubApi(routes("operator"));
    await page("/jobs/new", false);
    expect(await screen.findByText("lista de tareas")).toBeInTheDocument();
  });

  describe("save and simulate", () => {
    async function reachReview(extra: Record<string, () => Response>) {
      const mock = stubApi({
        ...routes(),
        "POST /jobs": () => json(jobFixture(), 201),
        ...extra,
      });
      await page();
      await reachOptions();
      await next();
      await next();
      await userEvent.click(screen.getByRole("button", { name: "Guardar y simular" }));
      return mock;
    }

    it("saves, starts a dry run and summarises its outcome", async () => {
      const mock = await reachReview({
        "POST /jobs/7/runs": () =>
          json(runFixture({ id: 50, dry_run: true, status: "queued" }), 202),
        "GET /runs/50": () =>
          json({
            ...runFixture({
              id: 50,
              dry_run: true,
              counters: {
                created: 3,
                updated: 1,
                skipped: 0,
                failed: 2,
                conflicts: 0,
                processed: 6,
              },
              error_count: 2,
            }),
            options: {},
            checkpoint: {},
            sample: [],
          }),
        "GET /runs/50/errors?limit=5": () =>
          json({
            items: [
              {
                id: 1,
                run_id: 50,
                record_ref: "u-2",
                message: "no value for name",
                side: "target",
                kind: "mapping",
                retryable: false,
                retried: false,
                payload: null,
              },
            ],
            total: 2,
          }),
      });
      const region = await screen.findByRole("region", { name: "Resultado de la simulación" });
      expect(await within(region).findByText("Creados")).toBeInTheDocument();
      expect(within(region).getByText("Creados").parentElement).toHaveTextContent(/Creados\s*3/);
      expect(within(region).getByText("Fallidos").parentElement).toHaveTextContent(/Fallidos\s*2/);
      expect(await within(region).findByText(/no value for name/)).toBeInTheDocument();
      expect(within(region).getByText(/u-2/)).toBeInTheDocument();
      expect(within(region).getByRole("link", { name: "Ver ejecución" })).toHaveAttribute(
        "href",
        "/runs/50",
      );
      expect(bodyOf(mock, "POST", "/admin/api/jobs")).toEqual(expectedBase);
      expect(bodyOf(mock, "POST", "/admin/api/jobs/7/runs")).toEqual({ dry_run: true });
      await userEvent.click(screen.getByRole("button", { name: "Volver a las tareas" }));
      expect(await screen.findByText("lista de tareas")).toBeInTheDocument();
    });

    it("keeps the saved job and explains when the dry run cannot start", async () => {
      await reachReview({
        "POST /jobs/7/runs": () => json({ error: "conflict", detail: "already running" }, 409),
      });
      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("La tarea se ha guardado");
      expect(alert).toHaveTextContent("Ya hay una ejecución en curso de esta tarea.");
      expect(screen.getByRole("button", { name: "Volver a las tareas" })).toBeInTheDocument();
    });

    it("shows the failure of a dry run that finished in error", async () => {
      await reachReview({
        "POST /jobs/7/runs": () =>
          json(runFixture({ id: 51, dry_run: true, status: "queued" }), 202),
        "GET /runs/51": () =>
          json({
            ...runFixture({ id: 51, dry_run: true, status: "failed", error: "remote unavailable" }),
            options: {},
            checkpoint: {},
            sample: [],
          }),
      });
      const region = await screen.findByRole("region", { name: "Resultado de la simulación" });
      expect(await within(region).findByText("Fallida")).toBeInTheDocument();
      expect(within(region).getByText("remote unavailable")).toBeInTheDocument();
    });
  });
});
