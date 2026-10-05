import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DryRunPanel } from "@/features/mappings/DryRunPanel";
import { dryRunFixture, mappingDocFixture } from "@/features/mappings/fixtures";
import { json, renderApp, stubApi } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const preview = (limit: number) => `POST /profiles/1/resources/clients/preview?limit=${limit}`;
const previewBody = {
  records: [{ id: "u-1", fields: { name: "Acme", email: " A@B.C " } }],
  schema: { name: "clients", label: "", id_field: "id", fields: [] },
};

async function renderPanel(props: Partial<React.ComponentProps<typeof DryRunPanel>> = {}) {
  const onResult = vi.fn();
  await renderApp(
    <DryRunPanel
      definition={mappingDocFixture()}
      sourceProfileId={1}
      targetProfileId={2}
      blocked={false}
      onResult={onResult}
      {...props}
    />,
  );
  return { onResult };
}

describe("DryRunPanel", () => {
  it("cannot run until both connections are chosen", async () => {
    stubApi({});
    await renderPanel({ sourceProfileId: null });
    expect(screen.getByRole("button", { name: "Ejecutar prueba" })).toBeDisabled();
    expect(screen.getByText(/Elige la conexión de origen y de destino/)).toBeInTheDocument();
  });

  it("cannot run while the rules have blocking errors", async () => {
    stubApi({});
    await renderPanel({ blocked: true });
    expect(screen.getByRole("button", { name: "Ejecutar prueba" })).toBeDisabled();
    expect(screen.getByText(/Corrige los errores de las reglas/)).toBeInTheDocument();
  });

  it("runs the draft and shows input and output per record, with rule errors", async () => {
    const mock = stubApi({
      "POST /mappings/dry-run": () => json(dryRunFixture),
      [preview(5)]: () => json(previewBody),
    });
    const { onResult } = await renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Ejecutar prueba" }));
    expect(await screen.findByText(/2 registros: 1 correcto, 1 con errores/)).toBeInTheDocument();

    const body = JSON.parse(
      String(mock.mock.calls.find(([url]) => String(url).endsWith("/mappings/dry-run"))![1]!.body),
    );
    expect(body).toEqual({
      definition: mappingDocFixture(),
      source_profile_id: 1,
      target_profile_id: 2,
      limit: 5,
    });

    const first = within(screen.getByRole("group", { name: "Registro u-1" }));
    expect(first.getByLabelText("Entrada")).toHaveTextContent("Acme");
    expect(first.getByLabelText("Salida")).toHaveTextContent("Acme");

    const second = within(screen.getByRole("group", { name: "Registro u-2" }));
    expect(second.getByText("Entrada no disponible")).toBeInTheDocument();
    expect(second.getByRole("list", { name: "Errores del registro" })).toHaveTextContent(
      "rules[0]",
    );
    expect(second.getByRole("list", { name: "Errores del registro" })).toHaveTextContent(
      "no value",
    );
    expect(onResult).toHaveBeenCalledWith(JSON.stringify(mappingDocFixture()), [
      { path: "rules[0]", severity: "error", message: "no value" },
    ]);
  });

  it("re-runs on demand with the chosen sample size", async () => {
    const mock = stubApi({
      "POST /mappings/dry-run": () => json(dryRunFixture),
      [preview(5)]: () => json(previewBody),
      [preview(20)]: () => json(previewBody),
    });
    await renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Ejecutar prueba" }));
    await screen.findByText(/2 registros/);
    await userEvent.selectOptions(screen.getByLabelText("Registros de muestra"), "20");
    await userEvent.click(screen.getByRole("button", { name: "Actualizar prueba" }));
    await screen.findByText(/2 registros/);
    const limits = mock.mock.calls
      .filter(([url]) => String(url).endsWith("/mappings/dry-run"))
      .map(([, init]) => (JSON.parse(String(init!.body)) as { limit: number }).limit);
    expect(limits).toEqual([5, 20]);
  });

  it("shows the findings of a rejected definition with their paths", async () => {
    stubApi({
      "POST /mappings/dry-run": () =>
        json(
          {
            error: "validation_error",
            detail: "x",
            issues: [{ path: "rules[0].target", severity: "error", message: "duplicate target" }],
          },
          422,
        ),
      [preview(5)]: () => json(previewBody),
    });
    const { onResult } = await renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Ejecutar prueba" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("rules[0].target");
    expect(alert).toHaveTextContent("duplicate target");
    expect(onResult).toHaveBeenCalledWith(JSON.stringify(mappingDocFixture()), [
      { path: "rules[0].target", severity: "error", message: "duplicate target" },
    ]);
  });

  it("explains an unreachable remote and the rate limit", async () => {
    stubApi({
      "POST /mappings/dry-run": () =>
        json({ error: "too_many_requests", detail: "" }, 429, { "Retry-After": "9" }),
      [preview(5)]: () => json(previewBody),
    });
    await renderPanel();
    await userEvent.click(await screen.findByRole("button", { name: "Ejecutar prueba" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("9 segundos");
  });
});
