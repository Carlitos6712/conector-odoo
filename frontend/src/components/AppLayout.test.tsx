import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { RequireAuth } from "@/auth/RequireAuth";
import { AppLayout } from "@/components/AppLayout";
import { LoginPage } from "@/pages/LoginPage";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

function Harness() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth />}>
        <Route element={<AppLayout />}>
          <Route path="/" element={<p>inicio</p>} />
        </Route>
      </Route>
    </Routes>
  );
}

afterEach(() => vi.unstubAllGlobals());

async function renderAs(role: Role) {
  const fetchMock = stubApi({
    "GET /auth/me": () => json(sessionBody(role)),
    "POST /auth/logout": () => new Response(null, { status: 204 }),
  });
  await renderApp(<Harness />, "/");
  await screen.findByText("inicio");
  return fetchMock;
}

describe("AppLayout navigation", () => {
  it("shows every section to an admin", async () => {
    await renderAs("admin");
    const nav = screen.getByRole("navigation", { name: "Navegación principal" });
    for (const name of [
      "Panel",
      "Conexiones",
      "Recursos",
      "Mapeos",
      "Tareas",
      "Ejecuciones",
      "Ajustes",
    ]) {
      expect(within(nav).getByRole("link", { name })).toBeInTheDocument();
    }
    expect(screen.queryByText(/solo lectura/i)).not.toBeInTheDocument();
  });

  it("keeps Ajustes for operators (account and preferences) and announces read-only mode", async () => {
    await renderAs("operator");
    const nav = screen.getByRole("navigation", { name: "Navegación principal" });
    expect(within(nav).getByRole("link", { name: "Ajustes" })).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Conexiones" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/solo lectura/i);
    expect(screen.getByText("Operador")).toBeInTheDocument();
  });

  it("logs out and returns to the login page", async () => {
    const fetchMock = await renderAs("admin");
    await userEvent.setup().click(screen.getByRole("button", { name: "Cerrar sesión" }));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([u]) => u === "/admin/api/auth/logout")).toBe(true);
  });
});
