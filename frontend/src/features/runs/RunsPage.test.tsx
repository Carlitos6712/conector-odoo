import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import { RUNS_PAGE_SIZE, runsQuery } from "@/features/runs/api";
import { RunsPage } from "@/features/runs/RunsPage";
import type { Run, RunFilters } from "@/features/runs/types";
import { json, renderApp, sessionBody, stubApi } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const jobs = [jobFixture(), jobFixture({ id: 8, name: "Pedidos a SUWE" })];

function routes(byQuery: Record<string, Run[]> = {}, fallback: Run[] = [runFixture()]) {
  const table: Record<string, () => Response> = {
    "GET /auth/me": () => json(sessionBody("operator")),
    "GET /jobs": () => json({ items: jobs }),
  };
  const queries: [RunFilters, number][] = [
    [{}, 1],
    [{}, 2],
    [{ status: "failed" }, 1],
    [{ jobId: 8 }, 1],
  ];
  for (const [filters, page] of queries) {
    const path = runsQuery(filters, page);
    table[`GET ${path}`] = () => json({ items: byQuery[path] ?? (page === 1 ? fallback : []) });
  }
  return table;
}

describe("RunsPage", () => {
  it("lists each run with job, trigger, dry-run flag, status, timing and counters", async () => {
    stubApi(
      routes({}, [
        runFixture({ id: 41, status: "partial", trigger: "schedule", duration_seconds: 65 }),
        runFixture({ id: 42, job_id: 8, dry_run: true, trigger: "webhook" }),
      ]),
    );
    await renderApp(<RunsPage />, "/runs");
    const table = await screen.findByRole("table", { name: "Ejecuciones" });
    const first = within(table).getByRole("link", { name: "#41" }).closest("tr")!;
    expect(first).toHaveTextContent("Clientes a Odoo");
    expect(first).toHaveTextContent("Programada");
    expect(first).toHaveTextContent("Parcial");
    expect(first).toHaveTextContent("1 min 5 s");
    expect(first).toHaveTextContent("6 procesados");
    expect(first).toHaveTextContent("3 creados");
    expect(within(table).getByRole("link", { name: "#41" })).toHaveAttribute("href", "/runs/41");
    const second = within(table).getByRole("link", { name: "#42" }).closest("tr")!;
    expect(second).toHaveTextContent("Pedidos a SUWE");
    expect(second).toHaveTextContent("Webhook");
    expect(second).toHaveTextContent("Simulación");
    expect(first).not.toHaveTextContent("Simulación");
  });

  it("falls back to the job id when the job is unknown", async () => {
    stubApi(routes({}, [runFixture({ job_id: 99 })]));
    await renderApp(<RunsPage />, "/runs");
    expect(await screen.findByText("Tarea #99")).toBeInTheDocument();
  });

  it("filters by status on the server and keeps the filter in the URL", async () => {
    const mock = stubApi(
      routes({ [runsQuery({ status: "failed" }, 1)]: [runFixture({ id: 50, status: "failed" })] }),
    );
    await renderApp(<RunsPage />, "/runs");
    await screen.findByRole("link", { name: "#41" });
    await userEvent.selectOptions(screen.getByLabelText("Estado"), "failed");
    expect(await screen.findByRole("link", { name: "#50" })).toBeInTheDocument();
    expect(mock.mock.calls.map((c) => c[0])).toContain(
      `/admin/api${runsQuery({ status: "failed" }, 1)}`,
    );
  });

  it("filters by job on the server", async () => {
    const mock = stubApi(routes({ [runsQuery({ jobId: 8 }, 1)]: [runFixture({ id: 60 })] }));
    await renderApp(<RunsPage />, "/runs");
    await screen.findByRole("link", { name: "#41" });
    await userEvent.selectOptions(await screen.findByLabelText("Tarea"), "Pedidos a SUWE");
    expect(await screen.findByRole("link", { name: "#60" })).toBeInTheDocument();
    expect(mock.mock.calls.map((c) => c[0])).toContain(`/admin/api${runsQuery({ jobId: 8 }, 1)}`);
  });

  it("starts from the filters in the URL", async () => {
    const mock = stubApi(routes({ [runsQuery({ jobId: 8 }, 1)]: [runFixture({ id: 61 })] }));
    await renderApp(<RunsPage />, "/runs?job=8");
    expect(await screen.findByRole("link", { name: "#61" })).toBeInTheDocument();
    expect(mock.mock.calls.map((c) => c[0])).not.toContain(`/admin/api${runsQuery({}, 1)}`);
  });

  it("filters by trigger and dry run on the loaded page and says so", async () => {
    stubApi(
      routes({}, [
        runFixture({ id: 41, trigger: "manual" }),
        runFixture({ id: 42, trigger: "schedule" }),
        runFixture({ id: 43, trigger: "schedule", dry_run: true }),
      ]),
    );
    await renderApp(<RunsPage />, "/runs");
    await screen.findByRole("link", { name: "#41" });
    await userEvent.selectOptions(screen.getByLabelText("Disparador"), "schedule");
    expect(screen.queryByRole("link", { name: "#41" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "#42" })).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Simulación"), "no");
    expect(screen.queryByRole("link", { name: "#43" })).not.toBeInTheDocument();
    expect(screen.getByText(/se aplican a las ejecuciones de esta página/i)).toBeInTheDocument();
  });

  it("pages through the history", async () => {
    const full = Array.from({ length: RUNS_PAGE_SIZE + 1 }, (_, i) => runFixture({ id: i + 1 }));
    const mock = stubApi(
      routes({
        [runsQuery({}, 1)]: full,
        [runsQuery({}, 2)]: [runFixture({ id: 900 })],
      }),
    );
    await renderApp(<RunsPage />, "/runs");
    await screen.findByRole("link", { name: "#1" });
    expect(screen.queryByRole("link", { name: `#${RUNS_PAGE_SIZE + 1}` })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByRole("link", { name: "#900" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
    expect(mock.mock.calls.map((c) => c[0])).toContain(`/admin/api${runsQuery({}, 2)}`);
  });

  it("shows an empty state, with a hint when filters are applied", async () => {
    stubApi(routes({}, []));
    await renderApp(<RunsPage />, "/runs");
    expect(await screen.findByText("Todavía no hay ejecuciones.")).toBeInTheDocument();
  });

  it("explains an empty result of a filtered search", async () => {
    stubApi(routes({ [runsQuery({ status: "failed" }, 1)]: [] }));
    await renderApp(<RunsPage />, "/runs?status=failed");
    expect(
      await screen.findByText("Ninguna ejecución coincide con los filtros."),
    ).toBeInTheDocument();
  });

  it("shows an error with retry", async () => {
    let fail = true;
    stubApi({
      ...routes(),
      [`GET ${runsQuery({}, 1)}`]: () => (fail ? json({}, 500) : json({ items: [runFixture()] })),
    });
    await renderApp(<RunsPage />, "/runs");
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByRole("link", { name: "#41" })).toBeInTheDocument();
  });

  it("announces how many runs are in progress in a live region", async () => {
    stubApi(
      routes({}, [
        runFixture({ id: 41, status: "running", finished_at: null, duration_seconds: null }),
        runFixture({ id: 42, status: "queued", finished_at: null, duration_seconds: null }),
        runFixture({ id: 43 }),
      ]),
    );
    await renderApp(<RunsPage />, "/runs");
    await screen.findByRole("table");
    expect(screen.getByRole("status")).toHaveTextContent("2 ejecuciones en curso");
  });

  it("refreshes while a run is active and stops once everything is finished", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current: Run[] = [
      runFixture({ id: 41, status: "running", finished_at: null, duration_seconds: null }),
    ];
    const mock = stubApi({
      ...routes(),
      [`GET ${runsQuery({}, 1)}`]: () => json({ items: current }),
    });
    await renderApp(<RunsPage />, "/runs");
    const calls = () => mock.mock.calls.filter((c) => c[0] === `/admin/api${runsQuery({}, 1)}`);
    await screen.findByRole("cell", { name: "En curso" });
    expect(calls()).toHaveLength(1);
    current = [runFixture({ id: 41, status: "succeeded" })];
    await vi.advanceTimersByTimeAsync(3100);
    expect(await screen.findByRole("cell", { name: "Correcta" })).toBeInTheDocument();
    expect(calls()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(calls()).toHaveLength(2);
  });
});
