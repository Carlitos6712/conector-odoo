import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { ConnectionWizardPage } from "@/features/connections/ConnectionWizardPage";
import {
  activationFailure,
  activeOdooFixture,
  failingTest,
  odooProfileFixture,
  passingTest,
  profileFixture,
} from "@/features/connections/fixtures";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

function Harness() {
  return (
    <Routes>
      <Route path="/connections" element={<p>lista de conexiones</p>} />
      <Route path="/connections/new" element={<ConnectionWizardPage />} />
      <Route path="/connections/:id/edit" element={<ConnectionWizardPage />} />
    </Routes>
  );
}

const SECRET = "tok-super-secret-123";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

function bodyOf(fetchMock: ReturnType<typeof stubApi>, method: string, path: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => url === `/admin/api${path}` && init?.method === method,
  );
  return call ? (JSON.parse(String(call[1]?.body)) as Record<string, unknown>) : undefined;
}

async function pickKind(user: ReturnType<typeof userEvent.setup>, name: string) {
  await user.click(await screen.findByRole("radio", { name }));
  await user.click(screen.getByRole("button", { name: "Siguiente" }));
}

async function fillRestBearer(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText("Nombre"), "SUWE");
  await user.type(screen.getByLabelText("URL base"), "https://api.suwe.test/v1");
  await user.type(screen.getByLabelText("Token Bearer"), SECRET);
}

function baseRoutes(role: Role = "admin") {
  return { "GET /auth/me": () => json(sessionBody(role)) };
}

describe("ConnectionWizard create", () => {
  it("requires a kind before continuing", async () => {
    stubApi(baseRoutes());
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("Elige un tipo de conexión.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Tipo de conexión" })).toBeInTheDocument();
  });

  it("walks the REST flow: kind, data, draft test, review and save", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles/test": () => json(passingTest),
      "POST /profiles": () => json(profileFixture(), 201),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    expect(screen.getByRole("heading", { name: "Datos de conexión" })).toBeInTheDocument();
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));

    expect(screen.getByRole("heading", { name: "Probar conexión" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Probar conexión" }));
    expect(await screen.findByText("Conexión correcta")).toBeInTheDocument();
    expect(bodyOf(fetchMock, "POST", "/profiles/test")).toMatchObject({
      type: "rest",
      auth_method: "bearer",
      base_url: "https://api.suwe.test/v1",
      secrets: { token: SECRET },
    });
    await user.click(screen.getByRole("button", { name: "Siguiente" }));

    expect(screen.getByRole("heading", { name: "Revisar y guardar" })).toBeInTheDocument();
    expect(screen.queryByText(SECRET)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
    const saved = bodyOf(fetchMock, "POST", "/profiles");
    expect(saved).toMatchObject({ name: "SUWE", secrets: { token: SECRET } });
    expect(saved).not.toHaveProperty("odoo_db");
  });

  it("walks the Odoo flow with database and login", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(odooProfileFixture, 201),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "Odoo");
    expect(screen.queryByLabelText("Tipo de autenticación")).not.toBeInTheDocument();
    await user.type(screen.getByLabelText("Nombre"), "Odoo producción");
    await user.type(screen.getByLabelText("URL base"), "https://odoo.example.com");
    await user.type(screen.getByLabelText("Base de datos"), "prod");
    await user.type(screen.getByLabelText("Usuario de Odoo"), "admin");
    await user.type(screen.getByLabelText("Clave de API"), "odoo-key-1234");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" })); // test is optional
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    expect(bodyOf(fetchMock, "POST", "/profiles")).toMatchObject({
      type: "odoo",
      auth_method: "api_key",
      odoo_db: "prod",
      odoo_login: "admin",
      secrets: { api_key: "odoo-key-1234" },
    });
  });

  it.each([
    [
      "Clave de API",
      ["Cabecera de la clave", "Clave de API"],
      ["Token Bearer", "URL del token", "Client ID"],
    ],
    ["Token Bearer", ["Token Bearer"], ["Clave de API", "URL del token", "Client ID"]],
    [
      "Client credentials (OAuth2)",
      ["URL del token", "Ámbito (scope)", "Client ID", "Client secret", "Usuario", "Contraseña"],
      ["Token Bearer", "Clave de API"],
    ],
    [
      "OpenID Connect",
      ["URL del token", "Ámbito (scope)", "Client ID", "Client secret"],
      ["Token Bearer", "Clave de API", "Usuario", "Contraseña"],
    ],
  ])("shows only the fields of the %s auth type", async (authType, shown, hidden) => {
    stubApi(baseRoutes());
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await user.selectOptions(screen.getByLabelText("Tipo de autenticación"), authType);
    for (const label of shown) expect(screen.getByLabelText(label)).toBeInTheDocument();
    for (const label of hidden) expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
  });

  it("accepts a username and password instead of a client secret for OAuth2", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(profileFixture(), 201),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await user.selectOptions(
      screen.getByLabelText("Tipo de autenticación"),
      "Client credentials (OAuth2)",
    );
    await user.type(screen.getByLabelText("Nombre"), "Authentik");
    await user.type(screen.getByLabelText("URL base"), "https://api.suwe.test/v1");
    await user.type(
      screen.getByLabelText("URL del token"),
      "https://auth.test/application/o/token/",
    );
    await user.type(screen.getByLabelText("Client ID"), "cid");
    await user.type(screen.getByLabelText("Usuario"), "alice");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    // client secret is still required while the password is missing
    expect(screen.getByRole("heading", { name: "Datos de conexión" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Contraseña"), "app-pass-1");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" })); // test is optional
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    const saved = bodyOf(fetchMock, "POST", "/profiles");
    expect(saved).toMatchObject({
      auth_method: "oauth2_client_credentials",
      username: "alice",
      secrets: { client_id: "cid", password: "app-pass-1" },
    });
    expect(saved?.secrets).not.toHaveProperty("client_secret");
  });

  it("keeps requiring the client secret when no username is typed", async () => {
    stubApi(baseRoutes());
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await user.selectOptions(
      screen.getByLabelText("Tipo de autenticación"),
      "Client credentials (OAuth2)",
    );
    await user.type(screen.getByLabelText("Nombre"), "IdP");
    await user.type(screen.getByLabelText("URL base"), "https://api.suwe.test/v1");
    await user.type(screen.getByLabelText("URL del token"), "https://auth.test/token");
    await user.type(screen.getByLabelText("Client ID"), "cid");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByLabelText("Client secret")).toHaveAttribute("aria-invalid", "true");
  });

  it("shows accessible inline errors and stays on the step", async () => {
    stubApi(baseRoutes());
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await user.type(screen.getByLabelText("URL base"), "ftp://nope");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    const name = screen.getByLabelText("Nombre");
    expect(name).toHaveAttribute("aria-invalid", "true");
    expect(name).toHaveAccessibleDescription("El nombre es obligatorio.");
    expect(screen.getByLabelText("URL base")).toHaveAccessibleDescription(
      "Introduce una URL válida que empiece por http:// o https://.",
    );
    expect(screen.getByLabelText("Token Bearer")).toHaveAccessibleDescription(
      "Este dato es obligatorio.",
    );
    expect(screen.getByRole("heading", { name: "Datos de conexión" })).toBeInTheDocument();
  });

  it("highlights the failing probe step with its message", async () => {
    stubApi({ ...baseRoutes(), "POST /profiles/test": () => json(failingTest) });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Probar conexión" }));
    const failing = await screen.findByRole("alert");
    expect(failing).toHaveTextContent("Autenticación");
    expect(failing).toHaveTextContent("the server rejected the credentials (HTTP 401)");
    const items = screen.getAllByRole("listitem").filter((li) => li.dataset.step);
    expect(items.map((li) => [li.dataset.step, li.dataset.state])).toEqual([
      ["url_valid", "ok"],
      ["reachable", "ok"],
      ["tls", "ok"],
      ["auth", "failed"],
    ]);
    // A failed test does not block saving.
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeEnabled();
  });

  it("goes back to the data step with a field error when the name is taken", async () => {
    stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json({ error: "conflict", detail: "name taken" }, 409),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    expect(await screen.findByRole("heading", { name: "Datos de conexión" })).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre")).toHaveAccessibleDescription(
      "Ya existe una conexión con este nombre.",
    );
  });

  it("keeps credentials out of the query cache, mutation cache and storage", async () => {
    stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(profileFixture(), 201),
    });
    const { queryClient, unmount } = await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    unmount();
    await waitFor(() => expect(queryClient.getMutationCache().getAll()).toHaveLength(0));
    const cached = JSON.stringify(
      queryClient
        .getQueryCache()
        .getAll()
        .map((q) => q.state.data),
    );
    expect(cached).not.toContain(SECRET);
    expect(JSON.stringify({ ...localStorage })).not.toContain(SECRET);
    expect(window.location.href).not.toContain(SECRET);
  });

  it("does not offer the wizard to operators", async () => {
    stubApi(baseRoutes("operator"));
    await renderApp(<Harness />, "/connections/new");
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Odoo" })).not.toBeInTheDocument();
  });
});

describe("ConnectionWizard edit", () => {
  const editRoutes = (extra: Record<string, () => Response | Promise<Response>> = {}) => ({
    ...baseRoutes(),
    "GET /profiles/1": () => json(profileFixture()),
    ...extra,
  });

  it("prefills non-secret data and never renders a stored secret", async () => {
    stubApi(editRoutes());
    await renderApp(<Harness />, "/connections/1/edit");
    expect(await screen.findByLabelText("Nombre")).toHaveValue("SUWE");
    expect(screen.getByLabelText("URL base")).toHaveValue("https://api.suwe.test/v1");
    const token = screen.getByLabelText("Token Bearer");
    expect(token).toHaveValue("");
    expect(token).toHaveAccessibleDescription(
      "Guardado. Déjalo en blanco para conservar el valor actual.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Atrás" }));
    expect(screen.getByRole("radio", { name: "API REST" })).toBeDisabled();
  });

  it("starts on the data step and keeps the stored secret when left blank", async () => {
    const fetchMock = stubApi(editRoutes({ "PUT /profiles/1": () => json(profileFixture()) }));
    await renderApp(<Harness />, "/connections/1/edit");
    const user = userEvent.setup();
    const name = await screen.findByLabelText("Nombre");
    await user.clear(name);
    await user.type(name, "SUWE v2");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    const sent = bodyOf(fetchMock, "PUT", "/profiles/1");
    expect(sent).toMatchObject({ name: "SUWE v2" });
    expect(sent).not.toHaveProperty("secrets");
  });

  it("sends a replacement secret only when one is typed", async () => {
    const fetchMock = stubApi(editRoutes({ "PUT /profiles/1": () => json(profileFixture()) }));
    await renderApp(<Harness />, "/connections/1/edit");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Token Bearer"), "new-token-456");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    expect(bodyOf(fetchMock, "PUT", "/profiles/1")).toMatchObject({
      secrets: { token: "new-token-456" },
    });
  });

  it("tests the stored connection when the secret was left blank", async () => {
    const fetchMock = stubApi(editRoutes({ "POST /profiles/1/test": () => json(passingTest) }));
    await renderApp(<Harness />, "/connections/1/edit");
    const user = userEvent.setup();
    await screen.findByLabelText("Nombre");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    const draft = screen.getByRole("button", { name: "Probar conexión" });
    expect(draft).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Probar la conexión guardada" }));
    expect(await screen.findByText("Conexión correcta")).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url === "/admin/api/profiles/test")).toBe(false);
  });

  it("shows an error state when the profile cannot be loaded", async () => {
    stubApi({
      ...baseRoutes(),
      "GET /profiles/9": () => json({ error: "not_found", detail: "" }, 404),
    });
    await renderApp(<Harness />, "/connections/9/edit");
    expect(
      await within(await screen.findByRole("alert")).findByText(/ya no existe/),
    ).toBeInTheDocument();
  });
});

describe("ConnectionWizard save and activate", () => {
  async function reachOdooReview(user: ReturnType<typeof userEvent.setup>) {
    await pickKind(user, "Odoo");
    await user.type(screen.getByLabelText("Nombre"), "Odoo producción");
    await user.type(screen.getByLabelText("URL base"), "https://odoo.example.com");
    await user.type(screen.getByLabelText("Base de datos"), "prod");
    await user.type(screen.getByLabelText("Usuario de Odoo"), "admin");
    await user.type(screen.getByLabelText("Clave de API"), "odoo-key-1234");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
  }

  it("is offered for Odoo connections only", async () => {
    stubApi(baseRoutes());
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(screen.getByRole("button", { name: "Guardar conexión" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar y activar" })).not.toBeInTheDocument();
  });

  it("saves the profile, then activates the saved id", async () => {
    const order: string[] = [];
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => {
        order.push("save");
        return json(odooProfileFixture, 201);
      },
      "PUT /odoo/active": () => {
        order.push("activate");
        return json(activeOdooFixture());
      },
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await reachOdooReview(user);
    await user.click(screen.getByRole("button", { name: "Guardar y activar" }));
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
    expect(order).toEqual(["save", "activate"]);
    expect(bodyOf(fetchMock, "PUT", "/odoo/active")).toEqual({ profile_id: 2 });
  });

  it("plain save does not activate", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(odooProfileFixture, 201),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await reachOdooReview(user);
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    await screen.findByText("lista de conexiones");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("does not activate when saving fails", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json({ error: "conflict", detail: "name taken" }, 409),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await reachOdooReview(user);
    await user.click(screen.getByRole("button", { name: "Guardar y activar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Ya existe una conexión/);
    expect(fetchMock.mock.calls.some(([url]) => url === "/admin/api/odoo/active")).toBe(false);
  });

  it("keeps the saved profile and shows the failing step when activation fails, then retries", async () => {
    let attempts = 0;
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(odooProfileFixture, 201),
      "PUT /odoo/active": () => {
        attempts += 1;
        return attempts === 1 ? json(activationFailure, 422) : json(activeOdooFixture());
      },
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await reachOdooReview(user);
    await user.click(screen.getByRole("button", { name: "Guardar y activar" }));

    const notice = await screen.findByText(/La conexión se ha guardado, pero no se pudo activar/);
    expect(notice.closest('[role="alert"]')).not.toBeNull();
    expect(document.querySelector('[data-state="failed"]')).toHaveAttribute("data-step", "auth");
    expect(screen.queryByText("lista de conexiones")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Guardar y activar" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Reintentar la activación" }));
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
    const creates = fetchMock.mock.calls.filter(
      ([url, init]) => url === "/admin/api/profiles" && init?.method === "POST",
    );
    expect(creates).toHaveLength(1);
  });

  it("can leave for the list after a failed activation, keeping the profile", async () => {
    stubApi({
      ...baseRoutes(),
      "POST /profiles": () => json(odooProfileFixture, 201),
      "PUT /odoo/active": () => json(activationFailure, 422),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await reachOdooReview(user);
    await user.click(screen.getByRole("button", { name: "Guardar y activar" }));
    await screen.findByText(/La conexión se ha guardado, pero no se pudo activar/);
    await user.click(screen.getByRole("button", { name: "Ir a las conexiones" }));
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
  });

  it("also works when editing an Odoo connection", async () => {
    const fetchMock = stubApi({
      ...baseRoutes(),
      "GET /profiles/2": () => json(odooProfileFixture),
      "PUT /profiles/2": () => json(odooProfileFixture),
      "PUT /odoo/active": () => json(activeOdooFixture()),
    });
    await renderApp(<Harness />, "/connections/2/edit");
    const user = userEvent.setup();
    await screen.findByLabelText("Nombre");
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar y activar" }));
    await screen.findByText("lista de conexiones");
    expect(bodyOf(fetchMock, "PUT", "/odoo/active")).toEqual({ profile_id: 2 });
  });
});

describe("ConnectionWizard vault not configured", () => {
  it("offers to generate the key when saving fails, then lets the user save again", async () => {
    let keyReady = false;
    const fetchMock = stubApi({
      ...baseRoutes(),
      "POST /profiles": () =>
        keyReady
          ? json(profileFixture(), 201)
          : json({ error: "vault_not_configured", detail: "no key" }, 503),
      "POST /vault/generate": () => {
        keyReady = true;
        return json({ configured: true, source: "file" }, 201);
      },
      "GET /vault/status": () => json({ configured: keyReady, source: keyReady ? "file" : null }),
    });
    await renderApp(<Harness />, "/connections/new");
    const user = userEvent.setup();
    await pickKind(user, "API REST");
    await fillRestBearer(user);
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Siguiente" }));
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));

    expect(
      await screen.findByText("El almacén de credenciales no está configurado en el servidor."),
    ).toBeInTheDocument();
    expect(screen.getByText(/copia de seguridad/i)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Generar clave" }));

    await waitFor(() =>
      expect(
        screen.queryByText("El almacén de credenciales no está configurado en el servidor."),
      ).not.toBeInTheDocument(),
    );
    expect(fetchMock.mock.calls.some(([url]) => url === "/admin/api/vault/generate")).toBe(true);
    await user.click(screen.getByRole("button", { name: "Guardar conexión" }));
    expect(await screen.findByText("lista de conexiones")).toBeInTheDocument();
  });
});
