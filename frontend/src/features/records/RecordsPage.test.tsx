import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import { pageFixture, partnerSchema } from "@/features/records/fixtures";
import { RecordsPage } from "@/features/records/RecordsPage";
import { storedFixture } from "@/features/resources/fixtures";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const LIST = "GET /profiles/2/records/res.partner?limit=50&offset=0";

function routes(role: Role, extra: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    [LIST]: () => json(pageFixture()),
    "GET /jobs": () => json({ items: [] }),
    ...extra,
  };
}

const callsTo = (mock: ReturnType<typeof stubApi>, method: string) =>
  mock.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);

describe("RecordsPage list", () => {
  it("lists the records of the first connection and offers every connection", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    const row = (await screen.findByText("Ada Lovelace")).closest("tr")!;
    expect(within(row).getByText("7")).toBeInTheDocument();
    expect(within(row).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(row).getByText("Londres")).toBeInTheDocument();
    const select = screen.getByLabelText("Conexión");
    expect(within(select).getByText("SUWE")).toBeInTheDocument();
    expect(within(select).getByText("Odoo producción")).toBeInTheDocument();
    expect(screen.getByLabelText("Modelo")).toHaveValue("res.partner");
  });

  it("explains when there is no connection", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => json({ items: [] }),
    });
    await renderApp(<RecordsPage />);
    expect(await screen.findByText(/Crea primero una conexión/)).toBeInTheDocument();
  });

  it("preselects the connection and resource given in the query string", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        ...RESOURCES,
        "GET /profiles/1/records/clients?limit=50&offset=0": () =>
          json(pageFixture({ items: [{ id: 5, fields: { name: "Acme" } }] })),
      }),
    );
    await renderApp(<RecordsPage />, "/records?profile=1&resource=clients");
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.getByLabelText("Conexión")).toHaveValue("1");
    expect(screen.getByLabelText("Recurso")).toHaveValue("clients");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/profiles/2/"))).toBe(false);
  });

  it("ignores a query-string profile that does not exist", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />, "/records?profile=99");
    expect(await screen.findByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByLabelText("Conexión")).toHaveValue("2");
  });

  it("searches with a debounce and resets to the first page", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        "GET /profiles/2/records/res.partner?limit=50&offset=0&search=ada": () =>
          json(pageFixture({ items: [pageFixture().items[0]!] })),
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Alan Turing");
    await userEvent.type(screen.getByRole("searchbox", { name: "Buscar" }), "ada");
    await waitFor(() => expect(screen.queryByText("Alan Turing")).not.toBeInTheDocument(), {
      timeout: 3000,
    });
    // One request for the final term: typing does not fire one per keystroke.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("search="))).toHaveLength(1);
  });

  it("paginates with limit and offset", async () => {
    stubApi(
      routes("admin", {
        [LIST]: () => json(pageFixture({ has_more: true })),
        "GET /profiles/2/records/res.partner?limit=50&offset=50": () =>
          json(pageFixture({ offset: 50, items: [{ id: 99, fields: { name: "Grace" } }] })),
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Grace")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  });

  it("shows an error with retry when the list fails", async () => {
    stubApi(
      routes("admin", {
        [LIST]: () => json({ error: "remote_unavailable", detail: "down" }, 502),
      }),
    );
    await renderApp(<RecordsPage />);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("never offers bulk selection or delete-all", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /todos|all/i })).not.toBeInTheDocument();
    expect(await screen.findAllByRole("button", { name: /^Eliminar/ })).toHaveLength(2);
  });

  it("is read-only for operators", async () => {
    stubApi(routes("operator"));
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByRole("button", { name: /^Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Eliminar/ })).not.toBeInTheDocument();
  });
});

const RESOURCES = {
  "GET /profiles/1/resources": () =>
    json({
      items: [
        storedFixture({ config: { name: "clients", label: "Clientes" } }),
        storedFixture({ config: { name: "orders", label: "Pedidos" } }),
      ],
      invalid: [],
    }),
};

const restPage = (overrides = {}) =>
  pageFixture({
    schema: {
      ...partnerSchema,
      name: "clients",
      id_field: "id",
      fields: [
        ...partnerSchema.fields,
        { ...partnerSchema.fields[1]!, name: "phone", label: "Teléfono" },
      ],
    },
    items: [
      {
        id: "c-1",
        fields: {
          name: "Acme",
          phone: "555",
          tags: ["a", "b"],
          address: { city: "Madrid" },
        },
      },
    ],
    ...overrides,
  });

describe("RecordsPage resource picker", () => {
  it("lists the resources of a REST connection and queries the first one", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        ...RESOURCES,
        "GET /profiles/1/records/clients?limit=50&offset=0": () => json(restPage()),
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    await userEvent.selectOptions(screen.getByLabelText("Conexión"), "1");
    const picker = await screen.findByLabelText("Recurso");
    expect(picker.tagName).toBe("SELECT");
    expect(within(picker).getByText("orders")).toBeInTheDocument();
    expect(await screen.findByText("Acme")).toBeInTheDocument();
    expect(screen.queryByLabelText("Modelo")).not.toBeInTheDocument();
    // No flash of the Odoo model against the REST connection.
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/profiles/1/records/res.partner")),
    ).toBe(false);
  });

  it("resets to the new connection's resource when the connection changes", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        ...RESOURCES,
        "GET /profiles/1/records/clients?limit=50&offset=0": () => json(restPage()),
        "GET /profiles/1/records/orders?limit=50&offset=0": () => json(restPage()),
      }),
    );
    await renderApp(<RecordsPage />, "/records?profile=1&resource=orders");
    const picker = await screen.findByLabelText("Recurso");
    await waitFor(() => expect(picker).toHaveValue("orders"));
    await userEvent.selectOptions(screen.getByLabelText("Conexión"), "2");
    expect(await screen.findByLabelText("Modelo")).toHaveValue("res.partner");
    await screen.findByText("Ada Lovelace");
    await userEvent.selectOptions(screen.getByLabelText("Conexión"), "1");
    await waitFor(() => expect(screen.getByLabelText("Recurso")).toHaveValue("clients"));
    expect(
      fetchMock.mock.calls.some(([url]) => String(url).includes("/profiles/2/records/orders")),
    ).toBe(false);
  });

  it("edits a REST record by its id", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        ...RESOURCES,
        "GET /profiles/1/records/clients?limit=50&offset=0": () => json(restPage()),
        "PATCH /profiles/1/records/clients/c-1": () =>
          json({ id: "c-1", fields: {}, propagation: [], warnings: [] }),
      }),
    );
    await renderApp(<RecordsPage />, "/records?profile=1");
    await userEvent.click(await screen.findByRole("button", { name: "Editar Acme" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Nombre"), "!");
    await userEvent.click(within(dialog).getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(callsTo(fetchMock, "PATCH")).toHaveLength(1));
  });
});

describe("RecordsPage volume controls", () => {
  it("changes the page size and goes back to the first page", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        [LIST]: () => json(pageFixture({ has_more: true })),
        "GET /profiles/2/records/res.partner?limit=50&offset=50": () =>
          json(pageFixture({ offset: 50, has_more: true })),
        "GET /profiles/2/records/res.partner?limit=100&offset=0": () => json(pageFixture()),
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    const size = screen.getByLabelText("Filas por página");
    expect(size).toHaveValue("50");
    expect(
      within(size)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["25", "50", "100"]);
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    await waitFor(() => expect(screen.getByText("Página 2")).toBeInTheDocument());
    await userEvent.selectOptions(size, "100");
    await waitFor(() => expect(screen.getByText("Página 1")).toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("limit=100&offset=0"))).toBe(
      true,
    );
  });

  it("shows which rows are on screen", async () => {
    stubApi(
      routes("admin", {
        [LIST]: () => json(pageFixture({ has_more: true })),
        "GET /profiles/2/records/res.partner?limit=50&offset=50": () =>
          json(pageFixture({ offset: 50 })),
      }),
    );
    await renderApp(<RecordsPage />);
    expect(await screen.findByText("Mostrando 1 a 2")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Mostrando 51 a 52")).toBeInTheDocument();
  });

  it("shows every column on demand without breaking on objects or arrays", async () => {
    stubApi(
      routes("admin", {
        ...RESOURCES,
        "GET /profiles/1/records/clients?limit=50&offset=0": () => json(restPage()),
      }),
    );
    await renderApp(<RecordsPage />, "/records?profile=1");
    await screen.findByText("Acme");
    expect(screen.queryByRole("columnheader", { name: "tags" })).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "Mostrar todas las columnas" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("columnheader", { name: "tags" })).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Teléfono" })).toBeInTheDocument();
    expect(screen.getByText('["a","b"]')).toBeInTheDocument();
    expect(screen.getByText('{"city":"Madrid"}')).toBeInTheDocument();
  });
});

describe("RecordsPage edit", () => {
  const PATCH = "PATCH /profiles/2/records/res.partner/7";

  async function openEdit() {
    await userEvent.click(await screen.findByRole("button", { name: "Editar Ada Lovelace" }));
    return screen.findByRole("dialog");
  }

  it("shows only writable fields and sends only the changed ones", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        [PATCH]: () =>
          json({
            id: 7,
            fields: { name: "Ada Lovelace", city: "París" },
            propagation: [],
            warnings: [],
          }),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openEdit();
    expect(within(dialog).getByLabelText("Nombre")).toHaveValue("Ada Lovelace");
    expect(within(dialog).queryByLabelText("Modificado")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("País")).not.toBeInTheDocument();
    const save = within(dialog).getByRole("button", { name: "Guardar" });
    expect(save).toBeDisabled();
    const city = within(dialog).getByLabelText("Ciudad");
    await userEvent.clear(city);
    await userEvent.type(city, "París");
    await userEvent.click(save);
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [, init] = callsTo(fetchMock, "PATCH")[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({ fields: { city: "París" } });
  });

  it("shows per-field errors and stays open", async () => {
    stubApi(
      routes("admin", {
        [PATCH]: () =>
          json(
            { error: "validation_error", detail: "cannot edit res.partner: email: bad format" },
            422,
          ),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openEdit();
    await userEvent.type(within(dialog).getByLabelText("Correo"), "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Guardar" }));
    expect(await within(dialog).findByText("bad format")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Correo")).toHaveAttribute("aria-invalid", "true");
  });

  it("reports a record that no longer exists", async () => {
    stubApi(
      routes("admin", {
        [PATCH]: () => json({ error: "resource_not_found", detail: "gone" }, 404),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openEdit();
    await userEvent.type(within(dialog).getByLabelText("Ciudad"), "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Guardar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/ya no existe/i);
  });
});

describe("RecordsPage delete", () => {
  const DELETE = "DELETE /profiles/2/records/res.partner/7";

  async function openDelete() {
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Ada Lovelace" }));
    return screen.findByRole("alertdialog");
  }

  it("asks for confirmation naming the record and model, without deleting yet", async () => {
    const fetchMock = stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    const dialog = await openDelete();
    expect(dialog).toHaveTextContent("Ada Lovelace");
    expect(dialog).toHaveTextContent("res.partner");
    expect(dialog).toHaveTextContent(/permanente/i);
    expect(dialog).toHaveTextContent(/no se puede deshacer/i);
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancelar" }));
    expect(callsTo(fetchMock, "DELETE")).toHaveLength(0);
  });

  it("deletes exactly that record once confirmed and refreshes the list", async () => {
    let deleted = false;
    const fetchMock = stubApi(
      routes("admin", {
        [DELETE]: () => {
          deleted = true;
          return new Response(null, { status: 204 });
        },
        [LIST]: () =>
          json(deleted ? pageFixture({ items: [pageFixture().items[1]!] }) : pageFixture()),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openDelete();
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar definitivamente" }));
    await waitFor(() => expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument());
    expect(callsTo(fetchMock, "DELETE")).toHaveLength(1);
    expect(screen.getByText("Alan Turing")).toBeInTheDocument();
  });

  it("surfaces the refusal message and keeps the dialog open", async () => {
    stubApi(
      routes("admin", {
        [DELETE]: () =>
          json(
            { error: "validation_error", detail: "cannot delete res.partner 7: used in invoices" },
            422,
          ),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openDelete();
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar definitivamente" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "cannot delete res.partner 7: used in invoices",
    );
    expect(screen.getByRole("alertdialog")).toBeInTheDocument();
  });
});

const outcome = (overrides = {}) => ({
  job_id: 3,
  job_name: "Clientes bidireccional",
  side: "target",
  action: "updated",
  counterpart_id: "c-9",
  warning: null,
  ...overrides,
});

describe("RecordsPage create", () => {
  const POST = "POST /profiles/2/records/res.partner";

  async function openCreate() {
    await userEvent.click(await screen.findByRole("button", { name: "Crear registro" }));
    return screen.findByRole("dialog");
  }

  it("is offered to admins only", async () => {
    stubApi(routes("operator"));
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    expect(screen.queryByRole("button", { name: "Crear registro" })).not.toBeInTheDocument();
  });

  it("shows the writable fields, never the id, and says the counterpart is created too", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    const dialog = await openCreate();
    expect(within(dialog).getByLabelText("Nombre")).toHaveValue("");
    expect(within(dialog).getByLabelText("Ciudad")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("ID")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Modificado")).not.toBeInTheDocument();
    expect(dialog).toHaveTextContent(/contraparte/i);
  });

  it("posts the filled fields, closes and reports the propagation", async () => {
    let created = false;
    const fetchMock = stubApi(
      routes("admin", {
        [POST]: () => {
          created = true;
          return json(
            {
              id: 9,
              fields: { name: "Grace" },
              propagation: [outcome({ action: "created" })],
              warnings: [],
            },
            201,
          );
        },
        [LIST]: () =>
          json(
            created
              ? pageFixture({ items: [{ id: 9, fields: { name: "Grace Hopper" } }] })
              : pageFixture(),
          ),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openCreate();
    await userEvent.type(within(dialog).getByLabelText("Nombre"), "Grace");
    await userEvent.click(within(dialog).getByRole("button", { name: "Crear" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const [, init] = callsTo(fetchMock, "POST")[0]!;
    expect(JSON.parse(String(init?.body))).toEqual({ fields: { name: "Grace", active: false } });
    expect(await screen.findByText("Grace Hopper")).toBeInTheDocument();
    const report = await screen.findByRole("status");
    expect(report).toHaveTextContent("Registro creado");
    expect(report).toHaveTextContent("Clientes bidireccional");
    expect(report).toHaveTextContent(/creado en la contraparte/i);
  });

  it("keeps the dialog open and shows per-field errors", async () => {
    stubApi(
      routes("admin", {
        [POST]: () =>
          json(
            { error: "validation_error", detail: "cannot edit res.partner: name: required" },
            422,
          ),
      }),
    );
    await renderApp(<RecordsPage />);
    const dialog = await openCreate();
    await userEvent.type(within(dialog).getByLabelText("Nombre"), "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Crear" }));
    expect(await within(dialog).findByText("required")).toBeInTheDocument();
  });
});

describe("RecordsPage propagation report", () => {
  const PATCH = "PATCH /profiles/2/records/res.partner/7";
  const DELETE = "DELETE /profiles/2/records/res.partner/7";

  async function editCity() {
    await userEvent.click(await screen.findByRole("button", { name: "Editar Ada Lovelace" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("Ciudad"), "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Guardar" }));
  }

  it("says clearly that nothing was propagated when no bidirectional job covers the resource", async () => {
    stubApi(
      routes("admin", {
        [PATCH]: () => json({ id: 7, fields: {}, propagation: [], warnings: [] }),
      }),
    );
    await renderApp(<RecordsPage />);
    await editCity();
    const report = await screen.findByRole("status");
    expect(report).toHaveTextContent("Registro actualizado");
    expect(report).toHaveTextContent(/ningún job bidireccional/i);
    expect(report).toHaveTextContent(/no se ha propagado nada/i);
  });

  it("lists each job with its action and shows the warnings of failed counterparts", async () => {
    stubApi(
      routes("admin", {
        [PATCH]: () =>
          json({
            id: 7,
            fields: {},
            propagation: [
              outcome(),
              outcome({
                job_id: 4,
                job_name: "Otro job",
                action: "failed",
                warning: "SUWE respondió 500",
              }),
            ],
            warnings: ["Otro job: SUWE respondió 500"],
          }),
      }),
    );
    await renderApp(<RecordsPage />);
    await editCity();
    const report = await screen.findByRole("status");
    expect(report).toHaveTextContent("Clientes bidireccional");
    expect(report).toHaveTextContent(/actualizado en la contraparte/i);
    expect(within(report).getByText("Otro job")).toBeInTheDocument();
    expect(report).toHaveTextContent(/fallido/i);
    expect(report).toHaveTextContent("SUWE respondió 500");
    expect(report).not.toHaveTextContent(/no se ha propagado nada/i);
    await userEvent.click(within(report).getByRole("button", { name: "Cerrar" }));
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("reads the DELETE 200 body and reports it", async () => {
    stubApi(
      routes("admin", {
        [DELETE]: () =>
          json({
            propagation: [outcome({ action: "deleted" })],
            warnings: [],
          }),
      }),
    );
    await renderApp(<RecordsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Ada Lovelace" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar definitivamente" }));
    const report = await screen.findByRole("status");
    expect(report).toHaveTextContent("Registro eliminado");
    expect(report).toHaveTextContent(/eliminado en la contraparte/i);
  });

  it("explains the counterpart in the edit and delete dialogs", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Editar Ada Lovelace" }));
    const edit = await screen.findByRole("dialog");
    expect(edit).toHaveTextContent(/contraparte en el otro sistema/i);
    expect(edit).toHaveTextContent(/gana el lado editado/i);
    expect(edit).toHaveTextContent(/nunca se deshace/i);
    await userEvent.click(within(edit).getByRole("button", { name: "Cancelar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Ada Lovelace" }));
    const del = await screen.findByRole("alertdialog");
    expect(del).toHaveTextContent(/contraparte en el otro sistema/i);
    expect(del).toHaveTextContent(/nunca se deshace/i);
  });
});

describe("RecordsPage sync now", () => {
  const matching = jobFixture({
    id: 7,
    name: "Odoo a SUWE",
    source: { profile_id: 2, resource: "res.partner" },
    target: { profile_id: 1, resource: "clients" },
    direction: "bidirectional",
  });
  const asTarget = jobFixture({
    id: 8,
    name: "SUWE a Odoo",
    source: { profile_id: 1, resource: "clients" },
    target: { profile_id: 2, resource: "res.partner" },
  });
  const unrelated = jobFixture({
    id: 9,
    name: "Otro recurso",
    source: { profile_id: 2, resource: "res.country" },
    target: { profile_id: 1, resource: "countries" },
  });
  const disabled = jobFixture({
    id: 10,
    name: "Apagado",
    enabled: false,
    target: { profile_id: 1, resource: "clients" },
    source: { profile_id: 2, resource: "res.partner" },
  });
  const jobs = () => json({ items: [matching, asTarget, unrelated, disabled] });

  it("is disabled with an explanation when no enabled job touches this resource", async () => {
    stubApi(routes("admin", { "GET /jobs": () => json({ items: [unrelated, disabled] }) }));
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Sincronizar ahora" })).toBeDisabled(),
    );
    expect(screen.getByText(/ningún job activo/i)).toBeInTheDocument();
  });

  it("lists the matching jobs, warns about bidirectional pushes and runs them for real", async () => {
    let started = false;
    const fetchMock = stubApi(
      routes("admin", {
        "GET /jobs": jobs,
        "POST /jobs/7/runs": () => json(runFixture({ id: 50, job_id: 7, status: "queued" }), 202),
        "POST /jobs/8/runs": () => json(runFixture({ id: 51, job_id: 8, status: "queued" }), 202),
        "GET /runs/50": () => json(runFixture({ id: 50, status: "succeeded" })),
        "GET /runs/51": () => json(runFixture({ id: 51, status: "succeeded" })),
        [LIST]: () => {
          const page = started
            ? pageFixture({ items: [{ id: 1, fields: { name: "Sincronizado" } }] })
            : pageFixture();
          return json(page);
        },
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    const button = await screen.findByRole("button", { name: "Sincronizar ahora" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Odoo a SUWE");
    expect(dialog).toHaveTextContent("SUWE a Odoo");
    expect(dialog).not.toHaveTextContent("Otro recurso");
    expect(dialog).not.toHaveTextContent("Apagado");
    expect(dialog).toHaveTextContent(/en ambos sentidos/i);
    started = true;
    await userEvent.click(within(dialog).getByRole("button", { name: "Sincronizar" }));
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    const posts = callsTo(fetchMock, "POST");
    expect(posts).toHaveLength(2);
    expect(JSON.parse(String(posts[0]![1]?.body))).toEqual({ dry_run: false });
    const links = await screen.findAllByRole("link", { name: "Ver ejecución" });
    expect(links.map((l) => l.getAttribute("href"))).toEqual(["/runs/50", "/runs/51"]);
    expect(await screen.findByText("Sincronizado")).toBeInTheDocument();
  });

  it("reports a job that could not be started without hiding the ones that did", async () => {
    stubApi(
      routes("admin", {
        "GET /jobs": jobs,
        "POST /jobs/7/runs": () => json({ error: "run_conflict", detail: "already running" }, 409),
        "POST /jobs/8/runs": () => json(runFixture({ id: 51, job_id: 8, status: "queued" }), 202),
        "GET /runs/51": () => json(runFixture({ id: 51, status: "succeeded" })),
      }),
    );
    await renderApp(<RecordsPage />);
    await screen.findByText("Ada Lovelace");
    const button = await screen.findByRole("button", { name: "Sincronizar ahora" });
    await waitFor(() => expect(button).toBeEnabled());
    await userEvent.click(button);
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Sincronizar" }),
    );
    expect(await screen.findByRole("link", { name: "Ver ejecución" })).toHaveAttribute(
      "href",
      "/runs/51",
    );
    expect(
      await screen.findByText(/Odoo a SUWE/, { selector: "[role=alert] *" }),
    ).toBeInTheDocument();
  });
});
