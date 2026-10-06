import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ConnectionsPage } from "@/features/connections/ConnectionsPage";
import {
  activationFailure,
  activeOdooFixture,
  noOdooFixture,
  odooProfileFixture,
  profileFixture,
} from "@/features/connections/fixtures";
import type { ActiveOdoo, Profile } from "@/features/connections/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const activeProfile: Profile = {
  ...odooProfileFixture,
  is_active: true,
  last_connected_at: "2026-03-01T10:00:00Z",
};
const otherOdoo: Profile = {
  ...odooProfileFixture,
  id: 3,
  name: "Odoo pruebas",
  base_url: "https://odoo-test.example.com",
};

function routes(
  role: Role,
  active: ActiveOdoo,
  items: Profile[] = [profileFixture(), activeProfile, otherOdoo],
) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items }),
    "GET /odoo/active": () => json(active),
  };
}

const panel = () => screen.getByRole("region", { name: "Conexión Odoo activa", hidden: true });

describe("active Odoo panel", () => {
  it("shows the profile that is live: name, URL, database, login and source", async () => {
    stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await within(await screen.findByRole("region", { name: "Conexión Odoo activa" })).findByText(
      "https://odoo.example.com",
    );
    const view = within(panel());
    expect(view.getByText("Odoo producción")).toBeInTheDocument();
    expect(view.getByText("prod")).toBeInTheDocument();
    expect(view.getByText("admin")).toBeInTheDocument();
    expect(view.getByText("Perfil")).toBeInTheDocument();
    expect(view.getByText("Activa")).toBeInTheDocument();
    expect(view.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("shows a prominent banner when no Odoo connection is active", async () => {
    stubApi(routes("admin", noOdooFixture));
    await renderApp(<ConnectionsPage />);
    const banner = await within(
      await screen.findByRole("region", { name: "Conexión Odoo activa" }),
    ).findByRole("alert");
    expect(banner).toHaveTextContent(
      "No hay ninguna conexión Odoo activa: la API de datos responde 503",
    );
    expect(
      within(panel()).getByRole("button", { name: "Elegir una conexión" }),
    ).toBeInTheDocument();
    expect(within(panel()).queryByRole("button", { name: "Desconectar" })).not.toBeInTheDocument();
  });

  it("offers to create an Odoo connection when there is none to choose from", async () => {
    stubApi(routes("admin", noOdooFixture, [profileFixture()]));
    await renderApp(<ConnectionsPage />);
    const link = await within(
      await screen.findByRole("region", { name: "Conexión Odoo activa" }),
    ).findByRole("link", { name: "Crear una conexión Odoo" });
    expect(link).toHaveAttribute("href", "/connections/new");
  });

  it("explains an environment connection is read-only and that a profile overrides it", async () => {
    stubApi(
      routes(
        "admin",
        activeOdooFixture({
          source: "env",
          profile_id: null,
          profile_name: null,
          last_connected_at: null,
        }),
      ),
    );
    await renderApp(<ConnectionsPage />);
    const view = within(await screen.findByRole("region", { name: "Conexión Odoo activa" }));
    expect(await view.findByText(/variables de entorno/)).toBeInTheDocument();
    expect(view.getByText("Entorno (heredada, solo lectura)")).toBeInTheDocument();
    expect(view.queryByRole("button", { name: "Desconectar" })).not.toBeInTheDocument();
  });

  it("warns when the stored profile could not be loaded and another source is used", async () => {
    stubApi(
      routes(
        "admin",
        activeOdooFixture({ source: "env", status: "fallback", warning: "profile 9 failed" }),
      ),
    );
    await renderApp(<ConnectionsPage />);
    const view = within(await screen.findByRole("region", { name: "Conexión Odoo activa" }));
    expect(await view.findByText(/no se pudo cargar al arrancar/)).toBeInTheDocument();
    expect(view.queryByText("profile 9 failed")).not.toBeInTheDocument();
  });

  it("is read-only for operators: sees the panel but has no actions", async () => {
    stubApi(routes("operator", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await within(await screen.findByRole("region", { name: "Conexión Odoo activa" })).findByText(
      "Odoo producción",
    );
    expect(screen.queryByRole("button", { name: "Desconectar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cambiar" })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usar como conexión activa/ }),
    ).not.toBeInTheDocument();
    expect(screen.getAllByText("Activa").length).toBeGreaterThan(0);
  });

  it("'Cambiar' moves focus to the profile list", async () => {
    stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Cambiar" }));
    expect(screen.getByRole("heading", { name: "Perfiles de conexión" })).toHaveFocus();
  });

  it("disconnects after confirming, then refreshes the panel", async () => {
    let active = activeOdooFixture();
    const fetchMock = stubApi({
      ...routes("admin", active),
      "GET /odoo/active": () => json(active),
      "DELETE /odoo/active": () => {
        active = noOdooFixture;
        return json(noOdooFixture);
      },
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Desconectar" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Desconectar" }));
    expect(await screen.findByText(/No hay ninguna conexión Odoo activa/)).toBeInTheDocument();
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("cancelling the disconnect dialog changes nothing", async () => {
    const fetchMock = stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Desconectar" }));
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancelar" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  });
});

describe("profile list: active badge and last connection", () => {
  it("marks the active Odoo profile and shows when it last connected", async () => {
    stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    const row = (await screen.findByText("Odoo pruebas")).closest("tr")!;
    expect(within(row).queryByText("Activa")).not.toBeInTheDocument();
    expect(within(row).getByText("Nunca")).toBeInTheDocument();
    const active = screen.getByText("Odoo producción", { selector: "td" }).closest("tr")!;
    expect(within(active).getByText("Activa")).toBeInTheDocument();
    const time = active.querySelector("time")!;
    expect(time).toHaveAttribute("datetime", "2026-03-01T10:00:00Z");
    expect(time.getAttribute("title")).toMatch(/2026/);
    expect(time.textContent).toMatch(/^hace /);
  });

  it("shows no last-connection data for REST rows", async () => {
    stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    const row = (await screen.findByText("SUWE")).closest("tr")!;
    expect(within(row).queryByText("Nunca")).not.toBeInTheDocument();
    expect(row.querySelector("time")).toBeNull();
  });

  it("offers 'Usar como conexión activa' on inactive Odoo rows only", async () => {
    stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await screen.findByText("Odoo pruebas");
    expect(
      screen.getByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Usar como conexión activa: SUWE" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Usar como conexión activa: Odoo producción" }),
    ).not.toBeInTheDocument();
  });
});

describe("activating an Odoo profile", () => {
  it("asks for confirmation and explains the switch is immediate", async () => {
    const fetchMock = stubApi(routes("admin", activeOdooFixture()));
    await renderApp(<ConnectionsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("de inmediato");
    expect(dialog).toHaveTextContent("API de datos");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("activates, refreshes the list and panel, and announces the result", async () => {
    let active = activeOdooFixture();
    let items = [profileFixture(), activeProfile, otherOdoo];
    const fetchMock = stubApi({
      "GET /auth/me": () => json(sessionBody("admin")),
      "GET /profiles": () => json({ items }),
      "GET /odoo/active": () => json(active),
      "PUT /odoo/active": () => {
        active = activeOdooFixture({ profile_id: 3, profile_name: "Odoo pruebas" });
        items = [
          profileFixture(),
          { ...activeProfile, is_active: false },
          { ...otherOdoo, is_active: true, last_connected_at: "2026-03-10T11:59:00Z" },
        ];
        return json(active);
      },
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Usar como conexión activa" }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(put[1]?.body))).toEqual({ profile_id: 3 });
    const row = screen.getByText("Odoo pruebas", { selector: "td *, td" }).closest("tr")!;
    await waitFor(() => expect(within(row).getByText("Activa")).toBeInTheDocument());
    expect(
      screen
        .getAllByRole("status")
        .some((el) => /Odoo pruebas es ahora la conexión activa/.test(el.textContent ?? "")),
    ).toBe(true);
  });

  it("shows the probe in progress while activating", async () => {
    stubApi({
      ...routes("admin", activeOdooFixture()),
      "PUT /odoo/active": () => new Promise<Response>(() => {}),
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Usar como conexión activa" }),
    );
    expect(await within(dialog).findByText("Probando la conexión…")).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Usar como conexión activa" }),
    ).toBeDisabled();
  });

  it("keeps the dialog open and highlights the failing step when the probe fails", async () => {
    stubApi({
      ...routes("admin", activeOdooFixture()),
      "PUT /odoo/active": () => json(activationFailure, 422),
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Usar como conexión activa" }),
    );
    expect(await within(dialog).findByText(/no se pudo activar/i)).toBeInTheDocument();
    const failed = dialog.querySelector('[data-state="failed"]')!;
    expect(failed).toHaveAttribute("data-step", "auth");
    expect(failed).toHaveTextContent("Falla en: Autenticación");
    // The previous connection is untouched.
    expect(within(panel()).getByText("Odoo producción")).toBeInTheDocument();
  });

  it("explains a missing profile (404)", async () => {
    stubApi({
      ...routes("admin", activeOdooFixture()),
      "PUT /odoo/active": () => json({ error: "not_found", detail: "gone" }, 404),
    });
    await renderApp(<ConnectionsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Usar como conexión activa: Odoo pruebas" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Usar como conexión activa" }),
    );
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("La conexión ya no existe.");
  });
});

describe("deleting the active profile", () => {
  it("explains that it must be disconnected or replaced first (409)", async () => {
    stubApi({
      ...routes("admin", activeOdooFixture()),
      "DELETE /profiles/2": () =>
        json({ error: "conflict", detail: "profile 2 is the active Odoo connection" }, 409),
    });
    await renderApp(<ConnectionsPage />);
    const row = (await screen.findByText("Odoo producción", { selector: "td" })).closest("tr")!;
    await userEvent.click(within(row).getByRole("button", { name: "Eliminar Odoo producción" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      /conexión Odoo activa.*Desconéctala o activa otra/,
    );
  });
});
