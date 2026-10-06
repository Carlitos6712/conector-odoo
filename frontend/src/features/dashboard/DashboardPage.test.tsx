import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { activeOdooFixture, noOdooFixture } from "@/features/connections/fixtures";
import type { ActiveOdoo } from "@/features/connections/types";
import { dashboardFixture } from "@/features/dashboard/fixtures";
import { DashboardPage } from "@/features/dashboard/DashboardPage";
import type { Dashboard } from "@/features/dashboard/types";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import type { Run } from "@/features/runs/types";
import { json, renderApp, sessionBody, stubApi } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const jobs = [
  jobFixture({ id: 7, name: "Clientes a Odoo", trigger: { kind: "schedule", cron: "0 * * * *" } }),
  jobFixture({ id: 8, name: "Pedidos a SUWE" }),
];
const today = (hour: number) => {
  const d = new Date();
  d.setHours(hour, 0, 0, 0);
  return d.toISOString();
};

interface Overrides {
  role?: "admin" | "operator";
  dashboard?: Dashboard | (() => Response);
  recent?: Run[] | (() => Response);
  jobList?: (() => Response) | undefined;
  odoo?: ActiveOdoo | (() => Response);
}

function routes({ role = "admin", dashboard, recent, jobList, odoo }: Overrides = {}) {
  const pick = <T,>(value: T | (() => Response) | undefined, fallback: T) =>
    typeof value === "function" ? (value as () => Response)() : json(value ?? fallback);
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /dashboard": () => pick(dashboard, dashboardFixture()),
    "GET /runs?limit=200": () =>
      typeof recent === "function" ? recent() : json({ items: recent ?? [] }),
    "GET /jobs": jobList ?? (() => json({ items: jobs })),
    "GET /odoo/active": () => pick(odoo, activeOdooFixture()),
  };
}

describe("DashboardPage", () => {
  it("shows the totals from the dashboard endpoint as links to their sections", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    const summary = await screen.findByRole("region", { name: "Resumen" });
    const connections = await within(summary).findByRole("link", { name: /Conexiones/ });
    expect(connections).toHaveTextContent("2");
    expect(connections).toHaveAttribute("href", "/connections");
    expect(within(summary).getByRole("link", { name: /Mapeos/ })).toHaveTextContent("3");
    const jobsCard = within(summary).getByRole("link", { name: /Tareas/ });
    expect(jobsCard).toHaveTextContent("4");
    expect(jobsCard).toHaveTextContent("3 activas");
    expect(jobsCard).toHaveAttribute("href", "/jobs");
  });

  it("breaks down the last 24 hours by status and counts failures", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    const card = await screen.findByRole("link", { name: /Últimas 24 horas/ });
    expect(card).toHaveTextContent("8");
    expect(card).toHaveTextContent("Correcta");
    expect(card).toHaveTextContent("5");
    const failures = screen.getByRole("link", { name: /Con fallos/ });
    expect(failures).toHaveTextContent("3");
    expect(failures).toHaveAttribute("href", "/runs?status=failed");
  });

  it("lists recent runs with job name, status and a link to the detail", async () => {
    stubApi(
      routes({
        dashboard: dashboardFixture({
          recent_runs: [
            runFixture({ id: 41, status: "partial", duration_seconds: 65 }),
            runFixture({ id: 42, job_id: 99, status: "failed" }),
          ],
        }),
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Ejecuciones recientes" });
    const row = (await within(section).findByRole("link", { name: "#41" })).closest("tr")!;
    expect(await within(row).findByText("Clientes a Odoo")).toBeInTheDocument();
    expect(row).toHaveTextContent("Parcial");
    expect(row).toHaveTextContent("1 min 5 s");
    expect(within(section).getByRole("link", { name: "#41" })).toHaveAttribute("href", "/runs/41");
    const unknown = within(section).getByRole("link", { name: "#42" }).closest("tr")!;
    expect(await within(unknown).findByText("Tarea #99")).toBeInTheDocument();
  });

  it("shows each job with its last status and next fire (scheduler or computed)", async () => {
    stubApi(
      routes({
        dashboard: dashboardFixture({
          scheduled: [
            {
              job_id: 7,
              name: "Clientes a Odoo",
              cron: "0 * * * *",
              next_fire: "2030-01-01T10:00:00Z",
            },
          ],
        }),
        recent: [runFixture({ id: 50, job_id: 7, status: "failed", started_at: today(9) })],
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Tareas" });
    const first = (await within(section).findByText("Clientes a Odoo")).closest("tr")!;
    expect(await within(first).findByRole("link", { name: /Fallida/ })).toHaveAttribute(
      "href",
      "/runs/50",
    );
    expect(first).toHaveTextContent(new Date("2030-01-01T10:00:00Z").toLocaleString("es-ES"));
    const second = within(section).getByText("Pedidos a SUWE").closest("tr")!;
    expect(second).toHaveTextContent("Sin ejecuciones");
    expect(second).toHaveTextContent("Manual");
  });

  it("estimates the next fire from the cron when the scheduler reports none", async () => {
    stubApi(
      routes({
        dashboard: dashboardFixture({
          scheduled: [{ job_id: 7, name: "Clientes a Odoo", cron: "0 * * * *", next_fire: null }],
        }),
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Tareas" });
    const row = (await within(section).findByText("Clientes a Odoo")).closest("tr")!;
    expect(row).toHaveTextContent("(estimada)");
  });

  it("lets admins run a job now after confirming, and hides it from operators", async () => {
    const mock = stubApi({
      ...routes(),
      "POST /jobs/7/runs": () => json(runFixture({ id: 77, status: "queued" }), 202),
    });
    await renderApp(<DashboardPage />, "/");
    await userEvent.click(
      await screen.findByRole("button", { name: "Ejecutar Clientes a Odoo ahora" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(mock.mock.calls.some((c) => c[1]?.method === "POST")).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Ejecutar" }));
    expect(await screen.findByText("Ejecución #77 iniciada")).toBeInTheDocument();
  });

  it("is read-only for operators", async () => {
    stubApi(routes({ role: "operator" }));
    await renderApp(<DashboardPage />, "/");
    await screen.findByText("Clientes a Odoo");
    expect(screen.queryByRole("button", { name: /ahora/ })).not.toBeInTheDocument();
  });

  it("collects what needs attention and links each item", async () => {
    stubApi(
      routes({
        dashboard: dashboardFixture({
          recent_failures: [runFixture({ id: 60, status: "failed" })],
          active_runs: [
            runFixture({
              id: 61,
              job_id: 8,
              status: "running",
              started_at: "2020-01-01T00:00:00Z",
              heartbeat_at: "2020-01-01T00:00:00Z",
            }),
          ],
        }),
        recent: [
          runFixture({ id: 70, job_id: 8, status: "failed", started_at: today(11) }),
          runFixture({ id: 69, job_id: 8, status: "failed", started_at: today(10) }),
        ],
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Requiere atención" });
    const failed = await within(section).findByRole("link", { name: /Ejecución #60/ });
    expect(failed).toHaveAttribute("href", "/runs/60");
    const stale = within(section).getByRole("link", { name: /Ejecución #61/ });
    expect(stale).toHaveTextContent("sin señal");
    expect(stale).toHaveAttribute("href", "/runs/61");
    const repeated = await within(section).findByRole("link", { name: /ha fallado/ });
    expect(repeated).toHaveTextContent("2 veces seguidas");
    expect(repeated).toHaveAttribute("href", "/runs?job=8");
  });

  it("says everything is fine when nothing needs attention", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Requiere atención" });
    expect(await within(section).findByText("Todo en orden.")).toBeInTheDocument();
  });

  it("draws the last 7 days with a text alternative and a table fallback", async () => {
    stubApi(
      routes({
        recent: [
          runFixture({ id: 1, status: "succeeded", started_at: today(10) }),
          runFixture({ id: 2, status: "succeeded", started_at: today(9) }),
          runFixture({ id: 3, status: "failed", started_at: today(8) }),
        ],
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Resultados de los últimos 7 días" });
    const chart = await within(section).findByRole("img");
    expect(chart).toHaveAccessibleName(/3 ejecuciones/);
    expect(chart).toHaveAccessibleName(/2 correctas/);
    expect(chart).toHaveAccessibleName(/1 fallida/);
    await userEvent.click(within(section).getByRole("button", { name: "Ver tabla" }));
    const table = within(section).getByRole("table", { name: "Ejecuciones por día" });
    expect(within(table).getAllByRole("row")).toHaveLength(8);
    expect(within(table).getAllByRole("row")[7]).toHaveTextContent("2");
  });

  it("explains an empty chart", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Resultados de los últimos 7 días" });
    expect(
      await within(section).findByText("Sin ejecuciones en los últimos 7 días."),
    ).toBeInTheDocument();
  });

  it("keeps the other sections when the dashboard request fails", async () => {
    stubApi(routes({ dashboard: () => json({ error: "internal", detail: "x" }, 500) }));
    await renderApp(<DashboardPage />, "/");
    const summary = await screen.findByRole("region", { name: "Resumen" });
    expect(await within(summary).findByRole("alert")).toBeInTheDocument();
    const recent = screen.getByRole("region", { name: "Ejecuciones recientes" });
    expect(await within(recent).findByRole("alert")).toBeInTheDocument();
    const chart = screen.getByRole("region", { name: "Resultados de los últimos 7 días" });
    expect(
      await within(chart).findByText("Sin ejecuciones en los últimos 7 días."),
    ).toBeInTheDocument();
  });

  it("keeps the rest when the latest-runs request fails", async () => {
    stubApi(routes({ recent: () => json({ error: "internal", detail: "x" }, 500) }));
    await renderApp(<DashboardPage />, "/");
    const chart = await screen.findByRole("region", { name: "Resultados de los últimos 7 días" });
    expect(await within(chart).findByRole("alert")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: /Conexiones/ })).toBeInTheDocument();
    const jobsSection = screen.getByRole("region", { name: "Tareas" });
    expect(await within(jobsSection).findByText("Clientes a Odoo")).toBeInTheDocument();
    expect(within(jobsSection).getAllByText("No disponible").length).toBeGreaterThan(0);
  });

  it("retries a failed section", async () => {
    let fail = true;
    stubApi(
      routes({
        jobList: () =>
          fail ? json({ error: "internal", detail: "x" }, 500) : json({ items: jobs }),
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const section = await screen.findByRole("region", { name: "Tareas" });
    const retry = await within(section).findByRole("button", { name: "Reintentar" });
    fail = false;
    await userEvent.click(retry);
    expect(await within(section).findByText("Clientes a Odoo")).toBeInTheDocument();
  });

  it("refreshes while a run is active and stops once nothing is running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = dashboardFixture({
      active_runs: [runFixture({ id: 41, status: "running" })],
    });
    const mock = stubApi({ ...routes(), "GET /dashboard": () => json(current) });
    await renderApp(<DashboardPage />, "/");
    const calls = () => mock.mock.calls.filter((c) => c[0] === "/admin/api/dashboard");
    await screen.findByRole("link", { name: /Conexiones/ });
    expect(calls()).toHaveLength(1);
    current = dashboardFixture();
    await vi.advanceTimersByTimeAsync(3100);
    expect(calls()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(calls()).toHaveLength(2);
  });

  it("refreshes everything on demand", async () => {
    const mock = stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    await screen.findByRole("link", { name: /Conexiones/ });
    const before = mock.mock.calls.filter((c) => c[0] === "/admin/api/dashboard").length;
    await userEvent.click(screen.getByRole("button", { name: "Actualizar" }));
    await vi.waitFor(() =>
      expect(mock.mock.calls.filter((c) => c[0] === "/admin/api/dashboard")).toHaveLength(
        before + 1,
      ),
    );
  });
});

describe("DashboardPage active Odoo", () => {
  it("shows a compact card with the active connection and a link to Connections", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    const card = await screen.findByRole("region", { name: "Odoo activo" });
    expect(await within(card).findByText("Odoo producción")).toBeInTheDocument();
    expect(within(card).getByText("Activa")).toBeInTheDocument();
    expect(within(card).getByText(/^hace /)).toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Ver conexiones" })).toHaveAttribute(
      "href",
      "/connections",
    );
  });

  it("describes an environment connection as legacy", async () => {
    stubApi(
      routes({
        odoo: activeOdooFixture({ source: "env", profile_id: null, profile_name: null }),
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const card = await screen.findByRole("region", { name: "Odoo activo" });
    expect(await within(card).findByText("Entorno (heredada, solo lectura)")).toBeInTheDocument();
  });

  it("flags a missing Odoo connection in the card and in the attention list", async () => {
    stubApi(routes({ odoo: noOdooFixture }));
    await renderApp(<DashboardPage />, "/");
    const card = await screen.findByRole("region", { name: "Odoo activo" });
    expect(await within(card).findByText("Sin conexión Odoo activa")).toBeInTheDocument();
    const attention = screen.getByRole("region", { name: "Requiere atención" });
    const link = await within(attention).findByRole("link", {
      name: /No hay ninguna conexión Odoo activa: la API de datos responde 503/,
    });
    expect(link).toHaveAttribute("href", "/connections");
    expect(within(attention).queryByText("Todo en orden.")).not.toBeInTheDocument();
  });

  it("flags the fallback case in the attention list", async () => {
    stubApi(
      routes({
        odoo: activeOdooFixture({ source: "env", status: "fallback", warning: "x" }),
      }),
    );
    await renderApp(<DashboardPage />, "/");
    const attention = screen.getByRole("region", { name: "Requiere atención" });
    expect(
      await within(attention).findByRole("link", { name: /no se pudo cargar al arrancar/ }),
    ).toHaveAttribute("href", "/connections");
  });

  it("raises no attention item while an Odoo connection is healthy", async () => {
    stubApi(routes());
    await renderApp(<DashboardPage />, "/");
    expect(await screen.findByText("Todo en orden.")).toBeInTheDocument();
  });

  it("keeps working when the active connection cannot be read", async () => {
    stubApi(routes({ odoo: () => json({ error: "internal_error", detail: "" }, 500) }));
    await renderApp(<DashboardPage />, "/");
    const card = await screen.findByRole("region", { name: "Odoo activo" });
    expect(await within(card).findByRole("alert")).toBeInTheDocument();
    expect(await screen.findByText("Todo en orden.")).toBeInTheDocument();
  });
});
