import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import { errorsQuery } from "@/features/runs/api";
import { runDetailFixture, runErrorFixture } from "@/features/runs/fixtures";
import { RunDetailPage } from "@/features/runs/RunDetailPage";
import type { RunDetail, RunError } from "@/features/runs/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const ERRORS = (page = 1, onlyUnretried = false) =>
  `GET ${errorsQuery(41, 20, { page, onlyUnretried })}`;

interface Setup {
  role?: Role;
  run?: RunDetail;
  errors?: RunError[];
  total?: number;
  extra?: Record<string, () => Response | Promise<Response>>;
}

function routes({
  role = "admin",
  run = runDetailFixture(),
  errors = [],
  total,
  extra,
}: Setup = {}) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /runs/41": () => json(run),
    "GET /jobs/7": () => json(jobFixture()),
    [ERRORS()]: () => json({ items: errors, total: total ?? errors.length }),
    ...extra,
  };
}

const view = (path = "/runs/41") =>
  renderApp(
    <Routes>
      <Route path="/runs/:id" element={<RunDetailPage />} />
    </Routes>,
    path,
  );

describe("RunDetailPage header", () => {
  it("shows status, trigger, job link, timing and counters", async () => {
    stubApi(routes({ run: runDetailFixture({ trigger: "schedule", duration_seconds: 65 }) }));
    await view();
    expect(await screen.findByRole("heading", { name: /Ejecución #41/ })).toBeInTheDocument();
    expect(screen.getAllByText("Correcta").length).toBeGreaterThan(0);
    expect(screen.getByText("Programada")).toBeInTheDocument();
    expect(await screen.findByRole("link", { name: "Clientes a Odoo" })).toHaveAttribute(
      "href",
      "/jobs/7/edit",
    );
    expect(screen.getByText("1 min 5 s")).toBeInTheDocument();
    const counters = screen.getByRole("region", { name: "Progreso" });
    expect(within(counters).getByText("Creados").nextSibling).toHaveTextContent("3");
    expect(within(counters).getByText("Omitidos").nextSibling).toHaveTextContent("2");
  });

  it("flags a dry run", async () => {
    stubApi(routes({ run: runDetailFixture({ dry_run: true }) }));
    await view();
    expect(await screen.findByText("Simulación")).toBeInTheDocument();
  });

  it("links to the run it retries", async () => {
    stubApi(routes({ run: runDetailFixture({ parent_run_id: 40 }) }));
    await view();
    expect(await screen.findByRole("link", { name: "#40" })).toHaveAttribute("href", "/runs/40");
    expect(screen.getByText(/Reintento de la ejecución/)).toBeInTheDocument();
  });

  it("shows where a resumable run would continue from", async () => {
    stubApi(
      routes({
        run: runDetailFixture({
          status: "failed",
          checkpoint: { pass: "reverse", last_id: "c-100", done: false },
        }),
      }),
    );
    await view();
    const region = await screen.findByRole("region", { name: "Punto de control" });
    expect(within(region).getByText("c-100")).toBeInTheDocument();
    expect(within(region).getByText("Destino → origen")).toBeInTheDocument();
  });

  it("shows the run-level error as plain text", async () => {
    stubApi(
      routes({ run: runDetailFixture({ status: "failed", error: "<b>boom</b> token=***" }) }),
    );
    await view();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("<b>boom</b> token=***");
    expect(alert.querySelector("b")).toBeNull();
  });

  it("hints that a silent run looks interrupted and can be resumed", async () => {
    const quiet = new Date(Date.now() - 20 * 60_000).toISOString();
    stubApi(
      routes({
        run: runDetailFixture({
          status: "running",
          finished_at: null,
          duration_seconds: null,
          heartbeat_at: quiet,
        }),
      }),
    );
    await view();
    expect(await screen.findByText(/parece interrumpida/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Reanudar" })).toBeInTheDocument();
  });

  it("does not hint anything for a healthy running run", async () => {
    stubApi(
      routes({
        run: runDetailFixture({
          status: "running",
          finished_at: null,
          duration_seconds: null,
          heartbeat_at: new Date().toISOString(),
        }),
      }),
    );
    await view();
    await screen.findByRole("heading", { name: /Ejecución #41/ });
    expect(screen.queryByText(/parece interrumpida/)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reanudar" })).not.toBeInTheDocument();
  });

  it("announces status changes while the run is refreshed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let current = runDetailFixture({
      status: "running",
      finished_at: null,
      duration_seconds: null,
      heartbeat_at: new Date().toISOString(),
    });
    stubApi(routes({ extra: { "GET /runs/41": () => json(current) } }));
    await view();
    await screen.findByRole("heading", { name: /Ejecución #41/ });
    const live = screen.getByRole("status");
    await waitFor(() => expect(live).toHaveTextContent("En curso"));
    current = runDetailFixture({ status: "succeeded" });
    await vi.advanceTimersByTimeAsync(1200);
    await waitFor(() => expect(live).toHaveTextContent("Correcta"));
  });

  it("says when the run does not exist", async () => {
    stubApi({
      ...routes(),
      "GET /runs/41": () => json({ error: "not_found", detail: "sync run 41 not found" }, 404),
    });
    await view();
    expect(await screen.findByText("La ejecución no existe.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Volver a ejecuciones" })).toHaveAttribute(
      "href",
      "/runs",
    );
  });

  it("rejects a non-numeric id without calling the API", async () => {
    const mock = stubApi({ "GET /auth/me": () => json(sessionBody()) });
    await view("/runs/abc");
    expect(await screen.findByText("La ejecución no existe.")).toBeInTheDocument();
    expect(mock.mock.calls.map((c) => c[0])).not.toContain("/admin/api/runs/NaN");
  });
});

describe("RunDetailPage errors", () => {
  const errors = [
    runErrorFixture({ id: 1, record_ref: "c-100", side: "source", kind: "rejected" }),
    runErrorFixture({
      id: 2,
      record_ref: "c-200",
      side: "target",
      kind: "remote",
      retryable: false,
      message: "<script>alert(1)</script>",
      payload: null,
    }),
  ];

  it("lists errors with side, kind, retryable flag, record and plain-text message", async () => {
    stubApi(routes({ errors, run: runDetailFixture({ status: "partial", error_count: 2 }) }));
    await view();
    const table = await screen.findByRole("table", { name: "Errores" });
    const first = within(table).getByText("c-100").closest("tr")!;
    expect(first).toHaveTextContent("Origen (A)");
    expect(first).toHaveTextContent("Rechazado");
    expect(first).toHaveTextContent("Sí");
    expect(first).toHaveTextContent("Odoo rejected the record");
    const second = within(table).getByText("c-200").closest("tr")!;
    expect(second).toHaveTextContent("Destino (B)");
    expect(second).toHaveTextContent("No");
    expect(second).toHaveTextContent("<script>alert(1)</script>");
    expect(second.querySelector("script")).toBeNull();
  });

  it("expands the redacted payload on demand", async () => {
    stubApi(routes({ errors, run: runDetailFixture({ status: "partial", error_count: 2 }) }));
    await view();
    const toggle = await screen.findByRole("button", { name: "Ver datos del registro c-100" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/"api_key"/)).not.toBeInTheDocument();
    await userEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const pre = screen.getByText(/"api_key"/);
    expect(pre.tagName).toBe("PRE");
    expect(pre).toHaveTextContent('"api_key": "***"');
    await userEvent.click(toggle);
    expect(screen.queryByText(/"api_key"/)).not.toBeInTheDocument();
  });

  it("offers no payload toggle for an error without payload", async () => {
    stubApi(routes({ errors, run: runDetailFixture({ status: "partial", error_count: 2 }) }));
    await view();
    await screen.findByText("c-200");
    expect(screen.queryByRole("button", { name: /registro c-200/ })).not.toBeInTheDocument();
  });

  it("filters the loaded page by kind and retryable flag", async () => {
    stubApi(routes({ errors, run: runDetailFixture({ status: "partial", error_count: 2 }) }));
    await view();
    await screen.findByText("c-100");
    await userEvent.selectOptions(screen.getByLabelText("Tipo"), "remote");
    expect(screen.queryByText("c-100")).not.toBeInTheDocument();
    expect(screen.getByText("c-200")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Tipo"), "");
    await userEvent.selectOptions(screen.getByLabelText("Reintentable"), "yes");
    expect(screen.getByText("c-100")).toBeInTheDocument();
    expect(screen.queryByText("c-200")).not.toBeInTheDocument();
  });

  it("asks the server for pending errors only", async () => {
    const mock = stubApi(
      routes({
        errors,
        run: runDetailFixture({ status: "partial", error_count: 2 }),
        extra: { [ERRORS(1, true)]: () => json({ items: [errors[0]], total: 1 }) },
      }),
    );
    await view();
    await screen.findByText("c-200");
    await userEvent.click(screen.getByRole("checkbox", { name: "Solo pendientes de reintento" }));
    await waitFor(() => expect(screen.queryByText("c-200")).not.toBeInTheDocument());
    expect(mock.mock.calls.map((c) => c[0])).toContain(
      `/admin/api${errorsQuery(41, 20, { page: 1, onlyUnretried: true }).replace("/admin/api", "")}`,
    );
  });

  it("pages through the errors using the server total", async () => {
    stubApi(
      routes({
        errors,
        total: 45,
        run: runDetailFixture({ status: "partial", error_count: 45 }),
        extra: {
          [ERRORS(2)]: () =>
            json({ items: [runErrorFixture({ id: 30, record_ref: "c-900" })], total: 45 }),
        },
      }),
    );
    await view();
    await screen.findByText("c-100");
    expect(screen.getByText("45 errores")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(await screen.findByText("c-900")).toBeInTheDocument();
    expect(screen.getByText("Página 2")).toBeInTheDocument();
  });

  it("says when there are no errors", async () => {
    stubApi(routes());
    await view();
    expect(await screen.findByText("Sin errores registrados.")).toBeInTheDocument();
  });

  it("points at the conflicts through the kind filter", async () => {
    stubApi(
      routes({
        errors: [runErrorFixture({ id: 5, record_ref: "c-500", kind: "conflict" }), errors[0]!],
        run: runDetailFixture({
          status: "partial",
          error_count: 2,
          counters: { ...runFixture().counters, conflicts: 1 },
        }),
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Ver conflictos" }));
    expect(screen.getByLabelText("Tipo")).toHaveValue("conflict");
    expect(screen.getByText("c-500")).toBeInTheDocument();
    expect(screen.queryByText("c-100")).not.toBeInTheDocument();
  });

  it("survives a failing error list and can retry it", async () => {
    let fail = true;
    stubApi(
      routes({
        run: runDetailFixture({ status: "partial", error_count: 1 }),
        extra: {
          [ERRORS()]: () => (fail ? json({}, 500) : json({ items: [errors[0]], total: 1 })),
        },
      }),
    );
    await view();
    const section = await screen.findByRole("region", { name: "Errores" });
    await waitFor(() => expect(within(section).getByRole("alert")).toBeInTheDocument());
    fail = false;
    await userEvent.click(within(section).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("c-100")).toBeInTheDocument();
  });
});

describe("RunDetailPage actions", () => {
  const running = runDetailFixture({
    status: "running",
    finished_at: null,
    duration_seconds: null,
    heartbeat_at: new Date().toISOString(),
  });

  it("cancels a running run after confirmation and refreshes the detail", async () => {
    const mock = stubApi(
      routes({
        run: running,
        extra: { "POST /runs/41/cancel": () => json({ ...running, cancel_requested: true }) },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Cancelar ejecución" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/siguiente lote/)).toBeInTheDocument();
    const before = mock.mock.calls.filter((c) => c[0] === "/admin/api/runs/41").length;
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancelar ejecución" }));
    expect(await screen.findByText("Cancelación solicitada.")).toBeInTheDocument();
    await waitFor(() =>
      expect(mock.mock.calls.filter((c) => c[0] === "/admin/api/runs/41").length).toBeGreaterThan(
        before,
      ),
    );
  });

  it("keeps the dialog open and explains a 409 on cancel", async () => {
    stubApi(
      routes({
        run: running,
        extra: {
          "POST /runs/41/cancel": () =>
            json({ error: "conflict", detail: "run 41 is not active" }, 409),
        },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Cancelar ejecución" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancelar ejecución" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "La ejecución ya no está en curso",
    );
  });

  it("resumes a failed run and links to it", async () => {
    stubApi(
      routes({
        run: runDetailFixture({ status: "failed" }),
        extra: {
          "POST /runs/41/resume": () => json(runFixture({ id: 41, status: "queued" }), 202),
        },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Reanudar" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reanudar" }));
    expect(await screen.findByText("Ejecución #41 reanudada.")).toBeInTheDocument();
  });

  it("explains a 409 on resume because the job is busy", async () => {
    stubApi(
      routes({
        run: runDetailFixture({ status: "failed" }),
        extra: {
          "POST /runs/41/resume": () =>
            json({ error: "conflict", detail: "sync job 7 already has an active run" }, 409),
        },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Reanudar" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reanudar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "La tarea ya tiene otra ejecución en curso",
    );
  });

  it("retries the failed records into a new linked run", async () => {
    stubApi(
      routes({
        run: runDetailFixture({ status: "partial", error_count: 2 }),
        errors: [runErrorFixture()],
        extra: {
          "POST /runs/41/retry-failed": () =>
            json(runFixture({ id: 50, parent_run_id: 41, status: "queued" }), 202),
        },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Reintentar fallidos" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reintentar fallidos" }));
    const toast = await screen.findByText("Reintento iniciado: ejecución #50.");
    expect(toast).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver ejecución" })).toHaveAttribute("href", "/runs/50");
  });

  it("maps 404 and 429 clearly", async () => {
    stubApi(
      routes({
        run: runDetailFixture({ status: "partial", error_count: 2 }),
        errors: [runErrorFixture()],
        extra: {
          "POST /runs/41/retry-failed": () =>
            json({ error: "rate_limited", detail: "slow down" }, 429, { "Retry-After": "7" }),
        },
      }),
    );
    await view();
    await userEvent.click(await screen.findByRole("button", { name: "Reintentar fallidos" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Reintentar fallidos" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("en 7 segundos");
  });

  it("shows no actions to operators", async () => {
    stubApi(
      routes({ role: "operator", run: runDetailFixture({ status: "failed", error_count: 2 }) }),
    );
    await view();
    await screen.findByRole("heading", { name: /Ejecución #41/ });
    expect(screen.queryByRole("button", { name: "Reanudar" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reintentar fallidos" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar ejecución" })).not.toBeInTheDocument();
  });

  it("offers nothing for a clean finished run", async () => {
    stubApi(routes());
    await view();
    await screen.findByRole("heading", { name: /Ejecución #41/ });
    expect(
      screen.queryByRole("button", { name: /Reanudar|Reintentar fallidos|Cancelar ejecución/ }),
    ).not.toBeInTheDocument();
  });

  it("says a cancellation is pending and hides the cancel button", async () => {
    stubApi(routes({ run: { ...running, cancel_requested: true } }));
    await view();
    expect(await screen.findByText(/Cancelación solicitada: se detendrá/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancelar ejecución" })).not.toBeInTheDocument();
  });
});
