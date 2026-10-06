import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { previewFixture } from "@/features/resources/fixtures";
import { formatCell, MAX_CELL_LENGTH } from "@/features/resources/format";
import { PreviewPanel } from "@/features/resources/PreviewPanel";
import type { PreviewResult } from "@/features/resources/types";
import { json, renderApp, stubApi } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const PATH = "POST /profiles/1/resources/clients/preview?limit=5";

describe("formatCell", () => {
  it("renders scalars, nulls and structures as text", () => {
    expect(formatCell(null).text).toBe("—");
    expect(formatCell(undefined).text).toBe("—");
    expect(formatCell(true).text).toBe("true");
    expect(formatCell(12.5).text).toBe("12.5");
    expect(formatCell(["a", 1]).text).toBe('["a",1]');
    expect(formatCell({ a: { b: 1 } }).text).toBe('{"a":{"b":1}}');
  });

  it("truncates long values and keeps the full text for the tooltip", () => {
    const cell = formatCell("y".repeat(500));
    expect(cell.text.length).toBe(MAX_CELL_LENGTH + 1);
    expect(cell.text.endsWith("…")).toBe(true);
    expect(cell.full).toHaveLength(500);
    expect(formatCell("short").full).toBeUndefined();
  });

  it("survives values that cannot be serialised", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(formatCell(circular).text).toBe("[objeto]");
  });
});

describe("PreviewPanel", () => {
  it("shows a loading state while the remote system answers", async () => {
    stubApi({ [PATH]: () => new Promise<Response>(() => {}) });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    expect(await screen.findByRole("status")).toHaveTextContent("Cargando");
  });

  it("renders a sample table and the inferred schema", async () => {
    stubApi({ [PATH]: () => json(previewFixture) });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    const records = await screen.findByRole("table", { name: "Registros de muestra" });
    expect(within(records).getByText("Acme")).toBeInTheDocument();
    expect(within(records).getByText("true")).toBeInTheDocument();
    expect(within(records).getByText('["a","b"]')).toBeInTheDocument();
    expect(within(records).getAllByText("—").length).toBeGreaterThan(0);
    const schema = screen.getByRole("table", { name: "Esquema inferido" });
    expect(within(schema).getByText("uuid")).toBeInTheDocument();
    expect(within(schema).getAllByText("string").length).toBeGreaterThan(0);
  });

  it("never renders HTML from the remote system", async () => {
    const hostile: PreviewResult = {
      ...previewFixture,
      records: [{ id: "1", fields: { name: "<img src=x onerror=alert(1)>" } }],
    };
    stubApi({ [PATH]: () => json(hostile) });
    const { container } = await renderApp(<PreviewPanel profileId={1} name="clients" />);
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("truncates very large values", async () => {
    const big: PreviewResult = {
      ...previewFixture,
      records: [{ id: "1", fields: { blob: "z".repeat(5000) } }],
    };
    stubApi({ [PATH]: () => json(big) });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    const cell = await screen.findByText(/^z+…$/);
    expect(cell.textContent!.length).toBeLessThan(200);
  });

  it("says so when the resource has no records", async () => {
    stubApi({ [PATH]: () => json({ ...previewFixture, records: [] }) });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    expect(await screen.findByText(/no ha devuelto registros/)).toBeInTheDocument();
  });

  it("shows the masked error of a failing remote system and can retry", async () => {
    let calls = 0;
    stubApi({
      [PATH]: () => {
        calls += 1;
        return calls === 1
          ? json(
              { error: "remote_unavailable", detail: "the remote system answered HTTP 503" },
              502,
            )
          : json(previewFixture);
      },
    });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No se ha podido contactar con la API remota");
    expect(alert).toHaveTextContent("the remote system answered HTTP 503");
    await userEvent.click(within(alert).getByRole("button", { name: "Reintentar" }));
    expect(await screen.findByText("Acme")).toBeInTheDocument();
  });

  it("explains rate limiting", async () => {
    stubApi({
      [PATH]: () => json({ error: "rate_limited", detail: "" }, 429, { "Retry-After": "7" }),
    });
    await renderApp(<PreviewPanel profileId={1} name="clients" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/7 segundos/);
  });
});
