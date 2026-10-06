import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "@/api/client";
import { App } from "@/App";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { json, renderApp, sessionBody, stubApi } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("renders placeholder sections inside the shell", async () => {
    stubApi({ "GET /auth/me": () => json(sessionBody()) });
    await renderApp(<App />, "/settings");
    expect(await screen.findByRole("heading", { name: "Ajustes" })).toBeInTheDocument();
    expect(screen.getByText(/disponible próximamente/)).toBeInTheDocument();
  });

  it("shows a not-found page for unknown routes", async () => {
    stubApi({ "GET /auth/me": () => json(sessionBody()) });
    await renderApp(<App />, "/nope");
    expect(
      await screen.findByRole("heading", { name: "Página no encontrada" }),
    ).toBeInTheDocument();
  });

  it("sends the user to login when a later call answers 401", async () => {
    stubApi({
      "GET /auth/me": () => json(sessionBody()),
      "GET /jobs": () => json({ error: "unauthorized", detail: "expired" }, 401),
    });
    function Probe() {
      const [on, setOn] = useState(false);
      useQuery({ queryKey: ["jobs"], queryFn: () => api.get("/jobs"), retry: false, enabled: on });
      return <button onClick={() => setOn(true)}>probe</button>;
    }
    await renderApp(
      <>
        <App />
        <Probe />
      </>,
      "/",
    );
    await screen.findByRole("heading", { name: "Panel" });
    await userEvent.setup().click(screen.getByRole("button", { name: "probe" }));
    expect(await screen.findByRole("heading", { name: "Iniciar sesión" })).toBeInTheDocument();
  });
});

describe("ErrorBoundary", () => {
  it("shows a recoverable message instead of a blank screen", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    function Bomb(): never {
      throw new Error("boom");
    }
    await renderApp(
      <ErrorBoundary>
        <Bomb />
      </ErrorBoundary>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Algo ha fallado");
    expect(screen.getByRole("button", { name: "Recargar" })).toBeInTheDocument();
  });
});
