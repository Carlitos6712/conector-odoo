import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { jobFixture, runFixture } from "@/features/jobs/fixtures";
import { JobsPage } from "@/features/jobs/JobsPage";
import type { Job } from "@/features/jobs/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

function routes(role: Role = "admin", jobs: Job[] = [jobFixture()], runs = [runFixture()]) {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /jobs": () => json({ items: jobs }),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    "GET /runs?limit=200": () => json({ items: runs }),
  };
}

const row = async (name = "Clientes a Odoo") => (await screen.findByText(name)).closest("tr")!;

describe("JobsPage", () => {
  it("summarises each job: route, direction, trigger and last run", async () => {
    stubApi(routes());
    await renderApp(<JobsPage />);
    const r = await row();
    expect(within(r).getByText("SUWE · clients")).toBeInTheDocument();
    expect(within(r).getByText("Odoo producción · res.partner")).toBeInTheDocument();
    expect(within(r).getByText("Origen → destino")).toBeInTheDocument();
    expect(within(r).getByText("Manual")).toBeInTheDocument();
    const last = await within(r).findByRole("link", { name: /Correcta/ });
    expect(last).toHaveAttribute("href", "/runs/41");
  });

  it("describes a schedule in words with its next fire time", async () => {
    stubApi(
      routes("admin", [
        jobFixture({
          trigger: { kind: "schedule", cron: "30 9 * * *" },
          next_fire: "2026-03-02T09:30:00Z",
        }),
      ]),
    );
    await renderApp(<JobsPage />);
    const r = await row();
    expect(within(r).getByText("Todos los días a las 09:30 UTC")).toBeInTheDocument();
    expect(within(r).getByText("30 9 * * *")).toBeInTheDocument();
    expect(within(r).queryByText("—")).not.toBeInTheDocument();
  });

  it("lists the events of a webhook trigger", async () => {
    stubApi(
      routes("admin", [
        jobFixture({
          trigger: { kind: "webhook", event_types: ["partner.created", "partner.updated"] },
        }),
      ]),
    );
    await renderApp(<JobsPage />);
    const r = await row();
    expect(within(r).getByText("Webhook: partner.created, partner.updated")).toBeInTheDocument();
  });

  it("shows the direction of a bidirectional job", async () => {
    stubApi(routes("admin", [jobFixture({ direction: "bidirectional" })]));
    await renderApp(<JobsPage />);
    expect(within(await row()).getByText("Bidireccional")).toBeInTheDocument();
  });

  it("says when a job never ran and survives a failing run history", async () => {
    stubApi({ ...routes("admin", [jobFixture()], []), "GET /runs?limit=200": () => json({}, 500) });
    await renderApp(<JobsPage />);
    expect(await within(await row()).findByText("No disponible")).toBeInTheDocument();
  });

  it("shows no last run for a job without runs", async () => {
    stubApi(routes("admin", [jobFixture()], []));
    await renderApp(<JobsPage />);
    expect(await within(await row()).findByText("Sin ejecuciones")).toBeInTheDocument();
  });

  it("offers every action to admins", async () => {
    stubApi(routes());
    await renderApp(<JobsPage />);
    await row();
    expect(screen.getByRole("link", { name: "Nueva tarea" })).toHaveAttribute("href", "/jobs/new");
    expect(screen.getByRole("link", { name: "Editar Clientes a Odoo" })).toHaveAttribute(
      "href",
      "/jobs/7/edit",
    );
    for (const name of [
      "Ejecutar Clientes a Odoo ahora",
      "Simular Clientes a Odoo",
      "Eliminar Clientes a Odoo",
    ]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("switch", { name: "Activa: Clientes a Odoo" })).toBeChecked();
  });

  it("is read-only for operators", async () => {
    stubApi(routes("operator"));
    await renderApp(<JobsPage />);
    await row();
    expect(screen.queryByRole("link", { name: "Nueva tarea" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Editar/ })).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Ejecutar|Simular|Eliminar/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Activa: Clientes a Odoo" })).toBeDisabled();
  });

  it("shows loading, empty and error states", async () => {
    stubApi(routes("admin", []));
    const { unmount } = await renderApp(<JobsPage />);
    expect(await screen.findByText(/Todavía no hay tareas/)).toBeInTheDocument();
    unmount();

    stubApi({ ...routes(), "GET /jobs": () => json({ error: "internal_error", detail: "" }, 500) });
    await renderApp(<JobsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Ha ocurrido un error inesperado.");
    expect(screen.getByRole("button", { name: "Reintentar" })).toBeInTheDocument();
  });

  it("explains the empty state differently to operators", async () => {
    stubApi(routes("operator", []));
    await renderApp(<JobsPage />);
    expect(await screen.findByText("Todavía no hay tareas.")).toBeInTheDocument();
  });

  it("disables a job by sending the whole definition with the flag off", async () => {
    const mock = stubApi({
      ...routes(),
      "PUT /jobs/7": () => json(jobFixture({ enabled: false })),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("switch", { name: "Activa: Clientes a Odoo" }));
    const call = mock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    const sent = JSON.parse(String((call[1] as RequestInit).body));
    expect(sent).toMatchObject({ name: "Clientes a Odoo", enabled: false });
    expect(sent).not.toHaveProperty("id");
  });

  it("reports a failed toggle", async () => {
    stubApi({
      ...routes(),
      "PUT /jobs/7": () => json({ error: "not_found", detail: "sync job 7 not found" }, 404),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("switch", { name: "Activa: Clientes a Odoo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/La tarea ya no existe/);
  });

  it("runs a job now after confirmation and links to the run", async () => {
    const mock = stubApi({
      ...routes(),
      "POST /jobs/7/runs": () => json(runFixture({ id: 50, status: "queued" }), 202),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Ejecutar Clientes a Odoo ahora" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    expect(mock).not.toHaveBeenCalledWith("/admin/api/jobs/7/runs", expect.anything());
    await userEvent.click(within(dialog).getByRole("button", { name: "Ejecutar" }));
    expect(await screen.findByText("Ejecución #50 iniciada")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ver ejecución" })).toHaveAttribute("href", "/runs/50");
    const call = mock.mock.calls.find(([url]) => url === "/admin/api/jobs/7/runs")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({ dry_run: false });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("explains that the job is already running", async () => {
    stubApi({
      ...routes(),
      "POST /jobs/7/runs": () =>
        json({ error: "conflict", detail: "job 7 is already running" }, 409),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Ejecutar Clientes a Odoo ahora" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Ejecutar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Ya hay una ejecución en curso de esta tarea.",
    );
  });

  it("explains that the job no longer exists", async () => {
    stubApi({
      ...routes(),
      "POST /jobs/7/runs": () => json({ error: "not_found", detail: "sync job 7 not found" }, 404),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(
      await screen.findByRole("button", { name: "Ejecutar Clientes a Odoo ahora" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Ejecutar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("La tarea ya no existe.");
  });

  it("starts a dry run straight away and reports it", async () => {
    const mock = stubApi({
      ...routes(),
      "POST /jobs/7/runs": () => json(runFixture({ id: 51, dry_run: true, status: "queued" }), 202),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Simular Clientes a Odoo" }));
    expect(await screen.findByText("Simulación #51 iniciada")).toBeInTheDocument();
    const call = mock.mock.calls.find(([url]) => url === "/admin/api/jobs/7/runs")!;
    expect(JSON.parse(String((call[1] as RequestInit).body))).toEqual({ dry_run: true });
  });

  it("reports a rate limited dry run with the delay", async () => {
    stubApi({
      ...routes(),
      "POST /jobs/7/runs": () =>
        json({ error: "too_many_requests", detail: "" }, 429, { "Retry-After": "12" }),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Simular Clientes a Odoo" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/12 segundos/);
  });

  it("deletes after confirmation", async () => {
    const mock = stubApi({
      ...routes(),
      "DELETE /jobs/7": () => new Response(null, { status: 204 }),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Clientes a Odoo" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(mock).toHaveBeenCalledWith(
      "/admin/api/jobs/7",
      expect.objectContaining({ method: "DELETE" }),
    );
  });

  it("explains why a job with runs cannot be deleted", async () => {
    stubApi({
      ...routes(),
      "DELETE /jobs/7": () => json({ error: "conflict", detail: "job has runs" }, 409),
    });
    await renderApp(<JobsPage />);
    await userEvent.click(await screen.findByRole("button", { name: "Eliminar Clientes a Odoo" }));
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Eliminar" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/tiene ejecuciones/);
  });
});
