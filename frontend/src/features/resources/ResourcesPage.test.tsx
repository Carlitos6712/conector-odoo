import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { previewFixture, storedFixture } from "@/features/resources/fixtures";
import { ResourcesPage } from "@/features/resources/ResourcesPage";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const second = profileFixture({ id: 3, name: "ERP" });

function routes(
  role: Role,
  listings: Record<number, unknown> = {
    1: { items: [storedFixture()], invalid: [] },
    3: { items: [storedFixture({ profile_id: 3, config: { name: "orders", label: "Pedidos" } })] },
  },
) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), second, odooProfileFixture] }),
    "GET /profiles/1/resources": () => json(listings[1]),
    "GET /profiles/3/resources": () => json(listings[3]),
  };
}

describe("ResourcesPage list", () => {
  it("shows a loading state first", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => new Promise<Response>(() => {}),
    });
    await renderApp(<ResourcesPage />);
    expect(await screen.findByRole("status")).toHaveTextContent("Cargando");
  });

  it("lists the resources of every REST connection with endpoint, pagination and source", async () => {
    stubApi(routes("admin"));
    await renderApp(<ResourcesPage />);
    const row = (await screen.findByText("clients")).closest("tr")!;
    expect(within(row).getByText("Clientes")).toBeInTheDocument();
    expect(within(row).getByText("SUWE")).toBeInTheDocument();
    expect(within(row).getByText("GET /organization/clients")).toBeInTheDocument();
    expect(within(row).getByText("Por páginas")).toBeInTheDocument();
    expect(within(row).getByText("Manual")).toBeInTheDocument();
    const other = screen.getByText("orders").closest("tr")!;
    expect(within(other).getByText("ERP")).toBeInTheDocument();
  });

  it("flags imported resources and resources without pagination", async () => {
    stubApi(
      routes("admin", {
        1: {
          items: [
            storedFixture({
              source: "openapi",
              config: { pagination: { ...storedFixture().config.pagination, strategy: "none" } },
            }),
          ],
          invalid: [],
        },
        3: { items: [] },
      }),
    );
    await renderApp(<ResourcesPage />);
    const row = (await screen.findByText("clients")).closest("tr")!;
    expect(within(row).getByText("OpenAPI")).toBeInTheDocument();
    expect(within(row).getByText("Ninguna")).toBeInTheDocument();
  });

  it("filters by connection and only asks for that profile", async () => {
    const fetchMock = stubApi(routes("admin"));
    await renderApp(<ResourcesPage />);
    await screen.findByText("orders");
    await userEvent.selectOptions(screen.getByLabelText("Conexión"), "SUWE");
    await waitFor(() => expect(screen.queryByText("orders")).not.toBeInTheDocument());
    expect(screen.getByText("clients")).toBeInTheDocument();
    expect(
      fetchMock.mock.calls.filter(([url]) => url === "/admin/api/profiles/3/resources"),
    ).toHaveLength(1);
  });

  it("warns about corrupt catalog rows without hiding the valid ones", async () => {
    stubApi(
      routes("admin", {
        1: { items: [storedFixture()], invalid: [{ name: "broken", reason: "bad json" }] },
        3: { items: [] },
      }),
    );
    await renderApp(<ResourcesPage />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/dañada/);
    expect(alert).toHaveTextContent("broken");
    expect(screen.getByText("clients")).toBeInTheDocument();
  });

  it("shows an empty state with create and import actions for admins", async () => {
    stubApi(routes("admin", { 1: { items: [] }, 3: { items: [] } }));
    await renderApp(<ResourcesPage />);
    expect(await screen.findByText(/Todavía no hay recursos/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Nuevo recurso" }).length).toBeGreaterThan(0);
    expect(screen.getAllByRole("link", { name: "Importar desde OpenAPI" }).length).toBeGreaterThan(
      0,
    );
  });

  it("asks for a REST connection first when there is none", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => json({ items: [odooProfileFixture] }),
    });
    await renderApp(<ResourcesPage />);
    expect(await screen.findByText(/Crea primero una conexión REST/)).toBeInTheDocument();
  });

  it("shows an error state that can retry", async () => {
    let calls = 0;
    stubApi({
      ...routes("admin"),
      "GET /profiles": () => {
        calls += 1;
        return calls === 1
          ? json({ error: "internal_error", detail: "" }, 500)
          : json({ items: [profileFixture(), second] });
      },
    });
    await renderApp(<ResourcesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("clients")).toBeInTheDocument();
  });

  it("hides every mutating action from operators", async () => {
    stubApi(routes("operator"));
    await renderApp(<ResourcesPage />);
    await screen.findByText("clients");
    expect(screen.queryByRole("link", { name: /Nuevo recurso/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Importar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Vista previa/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Eliminar/ })).not.toBeInTheDocument();
  });

  it("offers edit, preview and delete to admins", async () => {
    stubApi(routes("admin"));
    await renderApp(<ResourcesPage />);
    await screen.findByText("clients");
    expect(screen.getByRole("link", { name: "Editar clients" })).toHaveAttribute(
      "href",
      "/resources/1/clients/edit",
    );
    expect(screen.getByRole("button", { name: "Vista previa de clients" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eliminar clients" })).toBeInTheDocument();
  });

  it("opens the preview panel for a resource", async () => {
    stubApi({
      ...routes("admin"),
      "POST /profiles/1/resources/clients/preview?limit=5": () => json(previewFixture),
    });
    await renderApp(<ResourcesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Vista previa de clients" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("Acme")).toBeInTheDocument();
  });

  it("asks for confirmation before deleting and refreshes the list", async () => {
    let items = [storedFixture()];
    const fetchMock = stubApi({
      ...routes("admin"),
      "GET /profiles": () => json({ items: [profileFixture()] }),
      "GET /profiles/1/resources": () => json({ items, invalid: [] }),
      "DELETE /profiles/1/resources/clients": () => {
        items = [];
        return new Response(null, { status: 204 });
      },
    });
    await renderApp(<ResourcesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar clients" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    await waitFor(() => expect(screen.queryByText("clients")).not.toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("explains that a resource in use cannot be deleted", async () => {
    stubApi({
      ...routes("admin"),
      "DELETE /profiles/1/resources/clients": () =>
        json({ error: "conflict", detail: "resource is in use" }, 409),
    });
    await renderApp(<ResourcesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar clients" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/en uso/);
    expect(screen.getByText("clients")).toBeInTheDocument();
  });

  it("cancelling the dialog deletes nothing", async () => {
    const fetchMock = stubApi(routes("admin"));
    await renderApp(<ResourcesPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar clients" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancelar" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });
});
