import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MappingsPage } from "@/features/mappings/MappingsPage";
import { storedMappingFixture } from "@/features/mappings/fixtures";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

function routes(role: Role = "admin", items = [storedMappingFixture({ version: 3 })]) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /mappings": () => json({ items }),
  };
}

describe("MappingsPage", () => {
  it("lists mappings with their latest version and resources", async () => {
    stubApi(routes());
    await renderApp(<MappingsPage />);
    const row = (await screen.findByText("clients-to-partner")).closest("tr")!;
    expect(within(row).getByText("v3")).toBeInTheDocument();
    expect(within(row).getByText("clients")).toBeInTheDocument();
    expect(within(row).getByText("res.partner")).toBeInTheDocument();
  });

  it("offers create, edit, history and delete to admins", async () => {
    stubApi(routes());
    await renderApp(<MappingsPage />);
    await screen.findByText("clients-to-partner");
    expect(screen.getByRole("link", { name: "Nuevo mapeo" })).toHaveAttribute(
      "href",
      "/mappings/new",
    );
    expect(screen.getByRole("link", { name: "Editar clients-to-partner" })).toHaveAttribute(
      "href",
      "/mappings/clients-to-partner/edit",
    );
    expect(screen.getByRole("link", { name: "Historial de clients-to-partner" })).toHaveAttribute(
      "href",
      "/mappings/clients-to-partner/versions",
    );
    expect(screen.getByRole("button", { name: "Eliminar clients-to-partner" })).toBeInTheDocument();
  });

  it("is read-only for operators but still shows the history", async () => {
    stubApi(routes("operator"));
    await renderApp(<MappingsPage />);
    await screen.findByText("clients-to-partner");
    expect(screen.queryByRole("link", { name: "Nuevo mapeo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Eliminar/ })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver clients-to-partner" })).toHaveAttribute(
      "href",
      "/mappings/clients-to-partner/edit",
    );
    expect(
      screen.getByRole("link", { name: "Historial de clients-to-partner" }),
    ).toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    stubApi(routes("admin", []));
    await renderApp(<MappingsPage />);
    expect(await screen.findByText(/Todavía no hay mapeos/)).toBeInTheDocument();
  });

  it("deletes after confirmation", async () => {
    const mock = stubApi({
      ...routes(),
      "DELETE /mappings/clients-to-partner": () => new Response(null, { status: 204 }),
    });
    await renderApp(<MappingsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Eliminar clients-to-partner" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(mock).toHaveBeenCalledWith(
      "/admin/api/mappings/clients-to-partner",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("explains why a mapping in use cannot be deleted", async () => {
    stubApi({
      ...routes(),
      "DELETE /mappings/clients-to-partner": () =>
        json({ error: "conflict", detail: "mapping 'x' is used by a sync job" }, 409),
    });
    await renderApp(<MappingsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Eliminar clients-to-partner" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /está en uso por alguna tarea/,
    );
  });
});
