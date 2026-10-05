import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { csrfStore } from "@/api/client";
import { RequireAuth } from "@/auth/RequireAuth";
import { LoginPage } from "@/pages/LoginPage";
import { json, renderApp, sessionBody, stubApi } from "@/test/utils";

function Harness() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route path="/" element={<p>contenido protegido</p>} />
      </Route>
    </Routes>
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("RequireAuth", () => {
  it("redirects anonymous visitors to the login page", async () => {
    stubApi({ "GET /auth/me": () => json({ error: "unauthorized", detail: "no session" }, 401) });
    await renderApp(<Harness />, "/");
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(screen.queryByText("contenido protegido")).not.toBeInTheDocument();
  });

  it("renders the protected content and keeps the CSRF token in memory", async () => {
    stubApi({ "GET /auth/me": () => json(sessionBody("admin", "csrf-me")) });
    await renderApp(<Harness />, "/");
    expect(await screen.findByText("contenido protegido")).toBeInTheDocument();
    expect(csrfStore.get()).toBe("csrf-me");
  });

  it("shows a loading state while the session is being checked", async () => {
    stubApi({ "GET /auth/me": () => new Promise<Response>(() => {}) });
    await renderApp(<Harness />, "/");
    expect(screen.getByRole("status")).toHaveTextContent("Cargando");
  });

  it("offers a retry when the server cannot be reached", async () => {
    stubApi({ "GET /auth/me": () => json({ error: "internal_error", detail: "" }, 500) });
    await renderApp(<Harness />, "/");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });
});

describe("LoginPage", () => {
  async function fillAndSubmit() {
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Usuario"), "ana");
    await user.type(screen.getByLabelText("Contraseña"), "secret-pass-123");
    await user.click(screen.getByRole("button", { name: "Entrar" }));
  }

  it("signs in, stores the CSRF token and lands on the protected page", async () => {
    let signedIn = false;
    const fetchMock = stubApi({
      "GET /auth/me": () =>
        signedIn ? json(sessionBody()) : json({ error: "unauthorized", detail: "" }, 401),
      "POST /auth/login": () => {
        signedIn = true;
        return json(sessionBody("admin", "csrf-login"));
      },
    });
    await renderApp(<Harness />, "/");
    await fillAndSubmit();
    expect(await screen.findByText("contenido protegido")).toBeInTheDocument();
    expect(csrfStore.get()).toBe("csrf-login");
    const loginCall = fetchMock.mock.calls.find(([url]) => url === "/admin/api/auth/login");
    expect(JSON.parse(String(loginCall?.[1]?.body))).toEqual({
      username: "ana",
      password: "secret-pass-123",
    });
  });

  it("shows an accessible error on bad credentials and stays on the form", async () => {
    stubApi({
      "GET /auth/me": () => json({ error: "unauthorized", detail: "" }, 401),
      "POST /auth/login": () => json({ error: "invalid_credentials", detail: "bad" }, 401),
    });
    await renderApp(<Harness />, "/");
    await fillAndSubmit();
    expect(await screen.findByRole("alert")).toHaveTextContent("Usuario o contraseña incorrectos");
    expect(screen.getByLabelText("Usuario")).toBeInTheDocument();
  });

  it("explains the lockout when the server rate limits the login", async () => {
    stubApi({
      "GET /auth/me": () => json({ error: "unauthorized", detail: "" }, 401),
      "POST /auth/login": () =>
        json({ error: "too_many_attempts", detail: "" }, 429, { "Retry-After": "60" }),
    });
    await renderApp(<Harness />, "/");
    await fillAndSubmit();
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("60"));
  });
});
