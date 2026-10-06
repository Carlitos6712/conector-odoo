import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { pageFixture } from "@/features/records/fixtures";
import { RecordsPage } from "@/features/records/RecordsPage";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const LIST = "GET /profiles/2/records/res.partner?limit=25&offset=0";

function routes(role: Role, extra: Record<string, () => Response | Promise<Response>> = {}) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    [LIST]: () => json(pageFixture()),
    ...extra,
  };
}

const callsTo = (mock: ReturnType<typeof stubApi>, method: string) =>
  mock.mock.calls.filter(([, init]) => (init?.method ?? "GET") === method);

describe("RecordsPage list", () => {
  it("lists the records of the first Odoo connection, REST ones excluded", async () => {
    stubApi(routes("admin"));
    await renderApp(<RecordsPage />);
    const row = (await screen.findByText("Ada Lovelace")).closest("tr")!;
    expect(within(row).getByText("7")).toBeInTheDocument();
    expect(within(row).getByText("ada@example.com")).toBeInTheDocument();
    expect(within(row).getByText("Londres")).toBeInTheDocument();
    const select = screen.getByLabelText("Conexión");
    expect(within(select).queryByText("SUWE")).not.toBeInTheDocument();
    expect(within(select).getByText("Odoo producción")).toBeInTheDocument();
    expect(screen.getByLabelText("Modelo")).toHaveValue("res.partner");
  });

  it("explains when there is no Odoo connection", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => json({ items: [profileFixture()] }),
    });
    await renderApp(<RecordsPage />);
    expect(await screen.findByText(/Crea primero una conexión de Odoo/)).toBeInTheDocument();
  });

  it("searches with a debounce and resets to the first page", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        "GET /profiles/2/records/res.partner?limit=25&offset=0&search=ada": () =>
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
        "GET /profiles/2/records/res.partner?limit=25&offset=25": () =>
          json(pageFixture({ offset: 25, items: [{ id: 99, fields: { name: "Grace" } }] })),
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

describe("RecordsPage edit", () => {
  const PATCH = "PATCH /profiles/2/records/res.partner/7";

  async function openEdit() {
    await userEvent.click(await screen.findByRole("button", { name: "Editar Ada Lovelace" }));
    return screen.findByRole("dialog");
  }

  it("shows only writable fields and sends only the changed ones", async () => {
    const fetchMock = stubApi(
      routes("admin", {
        [PATCH]: () => json({ id: 7, fields: { name: "Ada Lovelace", city: "París" } }),
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
