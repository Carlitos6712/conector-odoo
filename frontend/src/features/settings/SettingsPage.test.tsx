import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { csrfStore } from "@/api/client";
import { SettingsPage } from "@/features/settings/SettingsPage";
import { THEME_STORAGE_KEY } from "@/features/settings/preferences";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

const USERS = [
  { id: 1, username: "ana", role: "admin", created_at: "2026-01-01T10:00:00Z" },
  { id: 2, username: "bea", role: "operator", created_at: "2026-02-02T10:00:00Z" },
  { id: 3, username: "carlos", role: "admin", created_at: "2026-03-03T10:00:00Z" },
];

type Routes = Parameters<typeof stubApi>[0];

function routes(role: Role = "admin", extra: Routes = {}): Routes {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /users": () => json({ items: USERS }),
    ...extra,
  };
}

const sent = (mock: ReturnType<typeof stubApi>, key: string) =>
  mock.mock.calls.filter(
    ([url, init]) =>
      `${(init as RequestInit | undefined)?.method ?? "GET"} ${String(url).replace("/admin/api", "")}` ===
      key,
  );
const bodyOf = (call: unknown[] | undefined) => JSON.parse(String((call?.[1] as RequestInit).body));

beforeEach(() => {
  localStorage.clear();
  document.documentElement.classList.remove("dark");
  csrfStore.set("csrf-1");
});
afterEach(() => vi.unstubAllGlobals());

async function renderPage(role: Role = "admin", extra: Routes = {}) {
  const mock = stubApi(routes(role, extra));
  const view = await renderApp(<SettingsPage />, "/settings");
  await screen.findByRole("heading", { name: "Ajustes" });
  return { mock, ...view };
}

describe("SettingsPage sections", () => {
  it("shows account, preferences, users and about to an admin", async () => {
    await renderPage("admin");
    for (const name of ["Mi cuenta", "Preferencias", "Usuarios", "Acerca de"]) {
      expect(await screen.findByRole("heading", { name })).toBeInTheDocument();
    }
  });

  it("hides the users section from operators and never requests the list", async () => {
    const { mock } = await renderPage("operator");
    expect(screen.getByRole("heading", { name: "Mi cuenta" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Preferencias" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Usuarios" })).not.toBeInTheDocument();
    expect(sent(mock, "GET /users")).toHaveLength(0);
  });

  it("describes the session in the read-only about section", async () => {
    await renderPage("operator");
    const about = screen.getByRole("region", { name: "Acerca de" });
    expect(await within(about).findByText("ana")).toBeInTheDocument();
    expect(within(about).getByText("Operador")).toBeInTheDocument();
    expect(within(about).getByText(/Sesión válida hasta/)).toBeInTheDocument();
  });
});

describe("My account: change password", () => {
  async function fill(current: string, next: string, confirm: string) {
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Contraseña actual"), current);
    await user.type(screen.getByLabelText("Nueva contraseña"), next);
    await user.type(screen.getByLabelText("Confirmar nueva contraseña"), confirm);
    return user;
  }
  const submit = () => screen.getByRole("button", { name: "Cambiar contraseña" });

  it("is available to operators and states the password policy", async () => {
    await renderPage("operator");
    expect(screen.getByText(/12 caracteres/)).toBeInTheDocument();
    expect(submit()).toBeDisabled();
  });

  it("sends current and new password, confirms and clears the form", async () => {
    const { mock } = await renderPage("operator", {
      "POST /auth/password": () => json(sessionBody("operator", "csrf-rotated")),
    });
    const user = await fill("old-password-123", "new-password-4567", "new-password-4567");
    await user.click(submit());
    expect(await screen.findByText("Contraseña actualizada")).toBeInTheDocument();
    expect(bodyOf(sent(mock, "POST /auth/password")[0])).toEqual({
      current_password: "old-password-123",
      new_password: "new-password-4567",
    });
    expect(csrfStore.get()).toBe("csrf-rotated");
    expect(screen.getByLabelText("Contraseña actual")).toHaveValue("");
    expect(screen.getByLabelText("Nueva contraseña")).toHaveValue("");
  });

  it("rejects a mismatched confirmation without calling the API", async () => {
    const { mock } = await renderPage("operator");
    const user = await fill("old-password-123", "new-password-4567", "different-password-1");
    await user.click(submit());
    expect(await screen.findByText("Las contraseñas no coinciden.")).toBeInTheDocument();
    expect(sent(mock, "POST /auth/password")).toHaveLength(0);
  });

  it("rejects a too-short new password without calling the API", async () => {
    const { mock } = await renderPage("admin");
    const user = await fill("old-password-123", "short", "short");
    await user.click(submit());
    expect(
      await screen.findByText("La nueva contraseña debe tener al menos 12 caracteres."),
    ).toBeInTheDocument();
    expect(sent(mock, "POST /auth/password")).toHaveLength(0);
  });

  it("shows a wrong current password next to its field", async () => {
    await renderPage("operator", {
      "POST /auth/password": () => json({ error: "invalid_current_password", detail: "nope" }, 422),
    });
    const user = await fill("wrong-password-12", "new-password-4567", "new-password-4567");
    await user.click(submit());
    expect(await screen.findByText("La contraseña actual no es correcta.")).toBeInTheDocument();
    expect(screen.getByLabelText("Contraseña actual")).toHaveAttribute("aria-invalid", "true");
  });

  it("reports the lockout with its delay", async () => {
    await renderPage("operator", {
      "POST /auth/password": () =>
        json({ error: "too_many_attempts", detail: "later" }, 429, { "Retry-After": "90" }),
    });
    const user = await fill("old-password-123", "new-password-4567", "new-password-4567");
    await user.click(submit());
    expect(await screen.findByText(/Demasiados intentos.*90 segundos/)).toBeInTheDocument();
  });
});

describe("Preferences", () => {
  it("switches the language at once and remembers it", async () => {
    await renderPage("operator");
    await userEvent.setup().selectOptions(screen.getByLabelText("Idioma"), "en");
    expect(await screen.findByRole("heading", { name: "Settings" })).toBeInTheDocument();
    expect(localStorage.getItem("conector.language")).toBe("en");
    expect(document.documentElement.lang).toBe("en");
  });

  it("applies and remembers the theme", async () => {
    await renderPage("operator");
    const user = userEvent.setup();
    await user.click(screen.getByRole("radio", { name: /Oscuro/ }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    await user.click(screen.getByRole("radio", { name: /Claro/ }));
    expect(document.documentElement).not.toHaveClass("dark");
  });

  it("reflects the stored theme", async () => {
    localStorage.setItem(THEME_STORAGE_KEY, "light");
    await renderPage("operator");
    expect(screen.getByRole("radio", { name: /Claro/ })).toBeChecked();
  });
});

const usersTable = async () => within(await screen.findByRole("table", { name: "Usuarios" }));
const rowOf = async (name: string) => (await usersTable()).getByText(name).closest("tr")!;

describe("Users management", () => {
  it("lists name, role and creation date", async () => {
    await renderPage();
    const bea = within(await rowOf("bea"));
    expect(bea.getByText("Operador")).toBeInTheDocument();
    expect(bea.getByText(/2026/)).toBeInTheDocument();
    expect(within(await rowOf("carlos")).getByText("Administrador")).toBeInTheDocument();
  });

  it("protects your own row: no delete, no demotion, no reset here", async () => {
    await renderPage();
    const ana = within(await rowOf("ana"));
    expect(ana.getByText("Tú")).toBeInTheDocument();
    expect(ana.getByRole("button", { name: "Cambiar rol de ana" })).toBeDisabled();
    expect(ana.getByRole("button", { name: "Eliminar a ana" })).toBeDisabled();
    expect(ana.queryByRole("button", { name: /Restablecer contraseña/ })).not.toBeInTheDocument();
  });

  it("creates a user with the chosen role and refreshes the list", async () => {
    const { mock } = await renderPage("admin", {
      "POST /users": () => json({ ...USERS[1], id: 9, username: "dani" }, 201),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Nuevo usuario" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Nuevo usuario" }));
    expect(dialog.getByText(/12 caracteres/)).toBeInTheDocument();
    await user.type(dialog.getByLabelText("Usuario"), "dani");
    await user.type(dialog.getByLabelText("Contraseña inicial"), "initial-password-1");
    await user.selectOptions(dialog.getByLabelText("Rol"), "admin");
    await user.click(dialog.getByRole("button", { name: "Crear usuario" }));
    expect(await screen.findByText("Usuario creado")).toBeInTheDocument();
    expect(bodyOf(sent(mock, "POST /users")[0])).toEqual({
      username: "dani",
      password: "initial-password-1",
      role: "admin",
    });
    expect(sent(mock, "GET /users").length).toBeGreaterThanOrEqual(2);
  });

  it("validates the initial password client-side", async () => {
    const { mock } = await renderPage();
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Nuevo usuario" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Nuevo usuario" }));
    await user.type(dialog.getByLabelText("Usuario"), "dani");
    await user.type(dialog.getByLabelText("Contraseña inicial"), "short");
    await user.click(dialog.getByRole("button", { name: "Crear usuario" }));
    expect(
      await dialog.findByText("La contraseña debe tener al menos 12 caracteres."),
    ).toBeInTheDocument();
    expect(sent(mock, "POST /users")).toHaveLength(0);
  });

  it("explains a taken username on 409", async () => {
    await renderPage("admin", {
      "POST /users": () => json({ error: "conflict", detail: "username taken" }, 409),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Nuevo usuario" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Nuevo usuario" }));
    await user.type(dialog.getByLabelText("Usuario"), "bea");
    await user.type(dialog.getByLabelText("Contraseña inicial"), "initial-password-1");
    await user.click(dialog.getByRole("button", { name: "Crear usuario" }));
    expect(await dialog.findByText("Ya existe un usuario con ese nombre.")).toBeInTheDocument();
  });

  it("changes another user's role, warning that sessions end", async () => {
    const { mock } = await renderPage("admin", {
      "PATCH /users/2": () => json({ ...USERS[1], role: "admin" }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cambiar rol de bea" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/cerrará sus sesiones/)).toBeInTheDocument();
    await user.selectOptions(dialog.getByLabelText("Rol"), "admin");
    await user.click(dialog.getByRole("button", { name: "Guardar" }));
    expect(await screen.findByText("Rol actualizado")).toBeInTheDocument();
    expect(bodyOf(sent(mock, "PATCH /users/2")[0])).toEqual({ role: "admin" });
  });

  it("shows the last-administrator conflict when demoting", async () => {
    await renderPage("admin", {
      "PATCH /users/3": () =>
        json({ error: "conflict", detail: "the last administrator cannot be demoted" }, 409),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Cambiar rol de carlos" }));
    const dialog = within(await screen.findByRole("dialog"));
    await user.selectOptions(dialog.getByLabelText("Rol"), "operator");
    await user.click(dialog.getByRole("button", { name: "Guardar" }));
    expect(
      await dialog.findByText("No se puede dejar el sistema sin administradores."),
    ).toBeInTheDocument();
  });

  it("resets a password after validating it", async () => {
    const { mock } = await renderPage("admin", {
      "PATCH /users/2": () => json(USERS[1]),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Restablecer contraseña de bea" }));
    const dialog = within(await screen.findByRole("dialog"));
    expect(dialog.getByText(/cerrarán todas sus sesiones/)).toBeInTheDocument();
    await user.type(dialog.getByLabelText("Nueva contraseña"), "tiny");
    await user.click(dialog.getByRole("button", { name: "Restablecer" }));
    expect(
      await dialog.findByText("La contraseña debe tener al menos 12 caracteres."),
    ).toBeInTheDocument();
    expect(sent(mock, "PATCH /users/2")).toHaveLength(0);
    await user.clear(dialog.getByLabelText("Nueva contraseña"));
    await user.type(dialog.getByLabelText("Nueva contraseña"), "reset-password-12");
    await user.click(dialog.getByRole("button", { name: "Restablecer" }));
    expect(await screen.findByText("Contraseña restablecida")).toBeInTheDocument();
    expect(bodyOf(sent(mock, "PATCH /users/2")[0])).toEqual({ password: "reset-password-12" });
  });

  it("asks for confirmation before deleting and then removes the user", async () => {
    const { mock } = await renderPage("admin", {
      "DELETE /users/2": () => new Response(null, { status: 204 }),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Eliminar a bea" }));
    const dialog = within(await screen.findByRole("alertdialog"));
    expect(dialog.getByText(/bea/)).toBeInTheDocument();
    expect(sent(mock, "DELETE /users/2")).toHaveLength(0);
    await user.click(dialog.getByRole("button", { name: "Eliminar" }));
    expect(await screen.findByText("Usuario eliminado")).toBeInTheDocument();
    expect(sent(mock, "DELETE /users/2")).toHaveLength(1);
  });

  it("keeps the dialog open and explains a delete conflict", async () => {
    await renderPage("admin", {
      "DELETE /users/3": () =>
        json({ error: "conflict", detail: "the last administrator cannot be deleted" }, 409),
    });
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Eliminar a carlos" }));
    const dialog = within(await screen.findByRole("alertdialog"));
    await user.click(dialog.getByRole("button", { name: "Eliminar" }));
    expect(
      await dialog.findByText("No se puede dejar el sistema sin administradores."),
    ).toBeInTheDocument();
  });

  it("shows an error state with retry when the list cannot be loaded", async () => {
    await renderPage("admin", {
      "GET /users": () => json({ error: "boom", detail: "" }, 500),
    });
    expect(await screen.findByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});
