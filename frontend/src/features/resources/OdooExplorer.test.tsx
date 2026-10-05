import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { ResourcesPage } from "@/features/resources/ResourcesPage";
import type { PreviewResult } from "@/features/resources/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const models = {
  items: [
    { name: "account.move", label: "Journal Entry" },
    { name: "res.partner", label: "Contact" },
    { name: "res.users", label: "User" },
  ],
};

const partnerSchema: PreviewResult = {
  records: [{ id: "7", fields: { name: "Acme" } }],
  schema: {
    name: "res.partner",
    label: "Contact",
    id_field: "id",
    fields: [
      {
        name: "name",
        type: "string",
        required: true,
        readonly: false,
        label: "Name",
        choices: null,
        relation: null,
      },
      {
        name: "parent_id",
        type: "integer",
        required: false,
        readonly: false,
        label: "Parent",
        choices: null,
        relation: "res.partner",
      },
    ],
  },
};

function routes(role: Role = "admin") {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    "GET /profiles/1/resources": () => json({ items: [], invalid: [] }),
  };
}

describe("Odoo model explorer", () => {
  it("is reachable from the connection filter", async () => {
    stubApi({ ...routes(), "POST /profiles/2/discover": () => json(models) });
    await renderApp(<ResourcesPage />);
    await userEvent.selectOptions(await screen.findByLabelText("Conexión"), "Odoo producción");
    expect(await screen.findByText("res.partner")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Nuevo recurso" })).not.toBeInTheDocument();
  });

  it("lists the discovered models, explains they are not stored and filters by search", async () => {
    stubApi({ ...routes(), "POST /profiles/2/discover": () => json(models) });
    await renderApp(<ResourcesPage />, "/?profile=2");
    expect(await screen.findByText("account.move")).toBeInTheDocument();
    expect(screen.getByText(/No se guardan en el catálogo/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Buscar modelo"), "contact");
    expect(screen.getByText("res.partner")).toBeInTheDocument();
    expect(screen.queryByText("account.move")).not.toBeInTheDocument();
    await userEvent.clear(screen.getByLabelText("Buscar modelo"));
    await userEvent.type(screen.getByLabelText("Buscar modelo"), "zzz");
    expect(screen.getByText("Ningún modelo coincide con la búsqueda.")).toBeInTheDocument();
  });

  it("shows the fields of the chosen model read-only", async () => {
    const fetchMock = stubApi({
      ...routes(),
      "POST /profiles/2/discover": () => json(models),
      "POST /profiles/2/resources/res.partner/preview?limit=1": () => json(partnerSchema),
    });
    await renderApp(<ResourcesPage />, "/?profile=2");
    await userEvent.click(await screen.findByRole("button", { name: /res\.partner/ }));
    const table = await screen.findByRole("table", { name: "Campos de res.partner" });
    const parent = within(table).getByText("parent_id").closest("tr")!;
    expect(within(parent).getByText("integer")).toBeInTheDocument();
    expect(within(parent).getByText("res.partner")).toBeInTheDocument();
    const name = within(table).getByText("name").closest("tr")!;
    expect(within(name).getByText("Sí")).toBeInTheDocument();
    expect(within(table).queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByText("Acme")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("reports a model whose fields cannot be read", async () => {
    stubApi({
      ...routes(),
      "POST /profiles/2/discover": () => json(models),
      "POST /profiles/2/resources/res.users/preview?limit=1": () =>
        json({ error: "permission_denied", detail: "no access" }, 403),
    });
    await renderApp(<ResourcesPage />, "/?profile=2");
    await userEvent.click(await screen.findByRole("button", { name: /res\.users/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Odoo ha denegado el acceso/);
  });

  it("shows a loading state and a retryable error while discovering", async () => {
    let calls = 0;
    stubApi({
      ...routes(),
      "POST /profiles/2/discover": () => {
        calls += 1;
        return calls === 1
          ? json({ error: "odoo_unavailable", detail: "connection refused" }, 502)
          : json(models);
      },
    });
    await renderApp(<ResourcesPage />, "/?profile=2");
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No se ha podido contactar con la API remota.");
    await userEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("res.partner")).toBeInTheDocument();
  });

  it("does not contact Odoo for operators", async () => {
    const fetchMock = stubApi(routes("operator"));
    await renderApp(<ResourcesPage />, "/?profile=2");
    expect(await screen.findByText(/Solo los administradores pueden explorar/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
});
