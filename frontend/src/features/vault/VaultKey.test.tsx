import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { csrfStore } from "@/api/client";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { json, renderApp, sessionBody, stubApi } from "@/test/utils";

beforeEach(() => csrfStore.set("csrf-1"));
afterEach(() => vi.unstubAllGlobals());

const base = {
  "GET /auth/me": () => json(sessionBody("admin")),
  "GET /users": () => json({ items: [] }),
};

describe("Settings vault section", () => {
  it("offers to generate the key, warns about the backup and refreshes the status", async () => {
    let configured = false;
    const mock = stubApi({
      ...base,
      "GET /vault/status": () =>
        json(
          configured ? { configured: true, source: "file" } : { configured: false, source: null },
        ),
      "POST /vault/generate": () => {
        configured = true;
        return json({ configured: true, source: "file" }, 201);
      },
    });
    await renderApp(<SettingsPage />, "/settings");
    const user = userEvent.setup();
    expect(await screen.findByText(/copia de seguridad/i)).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Generar clave" }));
    expect(await screen.findByText(/Clave guardada en el archivo/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generar clave" })).not.toBeInTheDocument();
    const post = mock.mock.calls.find(([url]) => url === "/admin/api/vault/generate");
    expect((post?.[1] as RequestInit).method).toBe("POST");
  });

  it("shows only the source when the key comes from the environment", async () => {
    stubApi({
      ...base,
      "GET /vault/status": () => json({ configured: true, source: "env" }),
    });
    await renderApp(<SettingsPage />, "/settings");
    expect(await screen.findByText(/variable de entorno ENCRYPTION_KEY/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Generar clave" })).not.toBeInTheDocument();
  });
});
