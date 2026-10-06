import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import {
  activeOdooFixture,
  failingTest,
  odooProfileFixture,
  passingTest,
  profileFixture,
} from "@/features/connections/fixtures";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

function routes(role: Role, items = [profileFixture(), odooProfileFixture]) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items }),
    "GET /odoo/active": () => json(activeOdooFixture()),
  };
}

describe("ConnectionsPage list", () => {
  it("shows a loading state first", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => new Promise<Response>(() => {}),
      "GET /odoo/active": () => json(activeOdooFixture()),
    });
    await renderApp(<ConnectionsPage />);
    const loading = await screen.findByText(/Cargando/);
    expect(loading.closest('[role="status"]')).not.toBeNull();
  });

  it("renders one row per profile with kind and base URL", async () => {
    stubApi(routes("admin"));
    await renderApp(<ConnectionsPage />);
    const row = (await screen.findByText("SUWE")).closest("tr")!;
    expect(within(row).getByText("API REST")).toBeInTheDocument();
    expect(within(row).getByText("https://api.suwe.test/v1")).toBeInTheDocument();
    const odoo = screen.getByText("Odoo producción", { selector: "td" }).closest("tr")!;
    expect(within(odoo).getByText("Odoo")).toBeInTheDocument();
    expect(within(odoo).getByText("Sin probar")).toBeInTheDocument();
  });

  it("shows an empty state with a create action for admins", async () => {
    stubApi(routes("admin", []));
    await renderApp(<ConnectionsPage />);
    expect(await screen.findByText(/Todavía no hay conexiones/)).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Nueva conexión" }).length).toBeGreaterThan(0);
  });

  it("shows an error state that can retry", async () => {
    let calls = 0;
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /odoo/active": () => json(activeOdooFixture()),
      "GET /profiles": () => {
        calls += 1;
        return calls === 1
          ? json({ error: "internal_error", detail: "" }, 500)
          : json({ items: [profileFixture()] });
      },
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("SUWE")).toBeInTheDocument();
  });

  it("hides every mutating action from operators", async () => {
    stubApi(routes("operator"));
    await renderApp(<ConnectionsPage />);
    await screen.findByText("SUWE");
    expect(screen.queryByRole("link", { name: "Nueva conexión" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Editar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Probar/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Eliminar/ })).not.toBeInTheDocument();
  });

  it("offers edit, test and delete to admins", async () => {
    stubApi(routes("admin"));
    await renderApp(<ConnectionsPage />);
    await screen.findByText("SUWE");
    expect(screen.getByRole("link", { name: "Editar SUWE" })).toHaveAttribute(
      "href",
      "/connections/1/edit",
    );
    expect(screen.getByRole("button", { name: "Probar SUWE" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Eliminar SUWE" })).toBeInTheDocument();
  });

  it("tests a saved profile and shows the outcome in the row", async () => {
    let result = passingTest;
    stubApi({ ...routes("admin"), "POST /profiles/1/test": () => json(result) });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Probar SUWE" }));
    const row = screen.getByText("SUWE").closest("tr")!;
    expect(await within(row).findByText("Conexión correcta")).toBeInTheDocument();
    result = failingTest;
    await userEvent.click(within(row).getByRole("button", { name: "Probar SUWE" }));
    expect(await within(row).findByText(/Falla en: Autenticación/)).toBeInTheDocument();
  });

  it("asks for confirmation before deleting and refreshes the list", async () => {
    let items = [profileFixture()];
    const fetchMock = stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /profiles": () => json({ items }),
      "GET /odoo/active": () => json(activeOdooFixture()),
      "DELETE /profiles/1": () => {
        items = [];
        return new Response(null, { status: 204 });
      },
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar SUWE" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    await waitFor(() => expect(screen.queryByText("SUWE")).not.toBeInTheDocument());
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("explains that a profile in use cannot be deleted", async () => {
    stubApi({
      ...routes("admin"),
      "DELETE /profiles/1": () => json({ error: "conflict", detail: "profile 1 is in use" }, 409),
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar SUWE" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/está en uso/);
    expect(screen.getByText("SUWE")).toBeInTheDocument();
  });

  it("cancelling the dialog deletes nothing", async () => {
    const fetchMock = stubApi(routes("admin"));
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar SUWE" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancelar" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });
});
