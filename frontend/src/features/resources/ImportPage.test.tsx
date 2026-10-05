import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { configFixture, noPagination, storedFixture } from "@/features/resources/fixtures";
import { ImportPage } from "@/features/resources/ImportPage";
import type { ImportReport } from "@/features/resources/types";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const report: ImportReport = {
  base_path: "/api/v1",
  candidates: [
    configFixture({ name: "invoices", label: "Facturas" }),
    configFixture({
      name: "orders",
      label: "Pedidos",
      list_endpoint: { method: "GET", path: "/orders" },
      get_endpoint: null,
      pagination: noPagination,
      items_path: "",
    }),
    configFixture({
      name: "products",
      list_endpoint: { method: "GET", path: "/products" },
      get_endpoint: null,
      pagination: noPagination,
    }),
  ],
  warnings: [
    "orders: no pagination parameters found in the list operation",
    "/health: the root path is not a resource, skipped",
  ],
};

const IMPORT = "POST /profiles/1/resources/import";

function base(role: Role = "admin") {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /profiles": () => json({ items: [profileFixture(), odooProfileFixture] }),
    "GET /profiles/1/resources": () => json({ items: [storedFixture()], invalid: [] }),
  };
}

async function renderImport(route = "/resources/import?profile=1") {
  return renderApp(
    <Routes>
      <Route path="/resources/import" element={<ImportPage />} />
      <Route path="/resources" element={<p>LISTA DE RECURSOS</p>} />
    </Routes>,
    route,
  );
}

const bodyOf = (call: unknown[] | undefined) =>
  JSON.parse(String((call?.[1] as RequestInit | undefined)?.body)) as Record<string, unknown>;

async function analyseUrl() {
  await userEvent.type(
    await screen.findByLabelText("URL del documento OpenAPI"),
    "https://api.test/openapi.json",
  );
  await userEvent.click(screen.getByRole("button", { name: "Analizar documento" }));
  await screen.findByRole("table", { name: "Candidatos" });
}

describe("ImportPage analysis", () => {
  it("is for admins only", async () => {
    stubApi(base("operator"));
    await renderImport();
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
  });

  it("only offers REST connections", async () => {
    stubApi(base());
    await renderImport();
    const select = await screen.findByLabelText("Conexión");
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Elige una conexión", "SUWE"]);
  });

  it("needs a source before analysing", async () => {
    stubApi(base());
    await renderImport();
    expect(await screen.findByRole("button", { name: "Analizar documento" })).toBeDisabled();
  });

  it("imports from a URL and lists candidates without saving anything", async () => {
    const fetchMock = stubApi({ ...base(), [IMPORT]: () => json(report) });
    await renderImport();
    await analyseUrl();
    const table = screen.getByRole("table", { name: "Candidatos" });
    const row = within(table).getByText("invoices").closest("tr")!;
    expect(within(row).getByText("GET /organization/clients")).toBeInTheDocument();
    expect(within(row).getByText("Por páginas")).toBeInTheDocument();
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/resources/import"));
    expect(bodyOf(call)).toEqual({ url: "https://api.test/openapi.json" });
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("imports a pasted document with an optional base path", async () => {
    const fetchMock = stubApi({ ...base(), [IMPORT]: () => json(report) });
    await renderImport();
    await userEvent.click(await screen.findByRole("tab", { name: "Pegar documento" }));
    expect(screen.getByRole("tab", { name: "Pegar documento" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByLabelText("URL del documento OpenAPI")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Documento OpenAPI (JSON o YAML)"));
    await userEvent.paste('{"openapi":"3.0.0"}');
    await userEvent.type(screen.getByLabelText(/Ruta base/), "/api/v1");
    await userEvent.click(screen.getByRole("button", { name: "Analizar documento" }));
    await screen.findByRole("table", { name: "Candidatos" });
    const call = fetchMock.mock.calls.find(([url]) => url.endsWith("/resources/import"));
    expect(bodyOf(call)).toEqual({ document: '{"openapi":"3.0.0"}', base_path: "/api/v1" });
  });

  it("shows every warning and explains that missing pagination is set by hand", async () => {
    stubApi({ ...base(), [IMPORT]: () => json(report) });
    await renderImport();
    await analyseUrl();
    const warnings = screen.getByRole("region", { name: "Advertencias (2)" });
    expect(within(warnings).getByText(/no pagination parameters found/)).toBeInTheDocument();
    expect(within(warnings).getByText(/root path is not a resource/)).toBeInTheDocument();
    expect(screen.getByText(/La paginación hay que indicarla a mano/)).toBeInTheDocument();
    const orders = screen.getByText("orders").closest("tr")!;
    expect(within(orders).getByText("Sin paginación detectada")).toBeInTheDocument();
    expect(within(orders).getByText("1 advertencia")).toBeInTheDocument();
    const invoices = screen.getByText("invoices").closest("tr")!;
    expect(within(invoices).queryByText(/advertencia/)).not.toBeInTheDocument();
  });

  it("shows the explanation of a document that cannot be imported", async () => {
    stubApi({
      ...base(),
      [IMPORT]: () => json({ error: "import_failed", detail: "the document is not OpenAPI" }, 422),
    });
    await renderImport();
    await userEvent.type(
      await screen.findByLabelText("URL del documento OpenAPI"),
      "https://api.test/x",
    );
    await userEvent.click(screen.getByRole("button", { name: "Analizar documento" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("No se ha podido importar el documento OpenAPI.");
    expect(alert).toHaveTextContent("the document is not OpenAPI");
  });
});

describe("ImportPage selection and saving", () => {
  it("starts with nothing selected and can select all", async () => {
    stubApi({ ...base(), [IMPORT]: () => json(report) });
    await renderImport();
    await analyseUrl();
    const save = screen.getByRole("button", { name: /Guardar seleccionados/ });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar todos" }));
    expect(screen.getByRole("button", { name: "Guardar seleccionados (3)" })).toBeEnabled();
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar orders" }));
    expect(screen.getByRole("button", { name: "Guardar seleccionados (2)" })).toBeEnabled();
  });

  it("flags candidates whose name already exists in the catalog", async () => {
    stubApi({
      ...base(),
      [IMPORT]: () => json({ ...report, candidates: [configFixture({ name: "clients" })] }),
    });
    await renderImport();
    await analyseUrl();
    expect(screen.getByText("Ya existe: se reemplazará")).toBeInTheDocument();
  });

  it("saves the selected candidates as openapi resources", async () => {
    const saved: string[] = [];
    const fetchMock = stubApi({
      ...base(),
      [IMPORT]: () => json(report),
      "PUT /profiles/1/resources/invoices": () => {
        saved.push("invoices");
        return json(storedFixture());
      },
      "PUT /profiles/1/resources/products": () => {
        saved.push("products");
        return json(storedFixture());
      },
    });
    await renderImport();
    await analyseUrl();
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoices" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar products" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar seleccionados (2)" }));
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
    expect(saved).toEqual(["invoices", "products"]);
    const puts = fetchMock.mock.calls.filter(([, init]) => init?.method === "PUT");
    expect(bodyOf(puts[0])).toMatchObject({ name: "invoices", source: "openapi" });
  });

  it("lets the user edit a candidate before saving it", async () => {
    const fetchMock = stubApi({
      ...base(),
      [IMPORT]: () => json(report),
      "PUT /profiles/1/resources/orders": () => json(storedFixture()),
    });
    await renderImport();
    await analyseUrl();
    await userEvent.click(screen.getByRole("button", { name: "Editar orders" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.selectOptions(
      within(dialog).getByLabelText("Estrategia de paginación"),
      "Por desplazamiento",
    );
    expect(within(dialog).getByLabelText("Parámetro de desplazamiento")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Aplicar cambios" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const row = screen.getByText("orders").closest("tr")!;
    expect(within(row).getByText("Por desplazamiento")).toBeInTheDocument();
    expect(within(row).queryByText("Sin paginación detectada")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar orders" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar seleccionados (1)" }));
    await screen.findByText("LISTA DE RECURSOS");
    const put = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(bodyOf(put)).toMatchObject({
      name: "orders",
      source: "openapi",
      pagination: { strategy: "offset", offset_param: "offset", limit_param: "limit" },
    });
  });

  it("does not apply an invalid edit", async () => {
    stubApi({ ...base(), [IMPORT]: () => json(report) });
    await renderImport();
    await analyseUrl();
    await userEvent.click(screen.getByRole("button", { name: "Editar orders" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.clear(within(dialog).getByLabelText("Campo identificador"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Aplicar cambios" }));
    expect(await within(dialog).findByText("Este dato es obligatorio.")).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("blocks saving selected candidates that are invalid", async () => {
    const fetchMock = stubApi({
      ...base(),
      [IMPORT]: () =>
        json({ ...report, candidates: [configFixture({ name: "orders", id_field: "" })] }),
    });
    await renderImport();
    await analyseUrl();
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar orders" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar seleccionados (1)" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Revisa los recursos marcados/);
    expect(within(screen.getByText("orders").closest("tr")!).getByText("Revisar")).toBeVisible();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("keeps what was saved when a later candidate fails and does not resend it", async () => {
    let productCalls = 0;
    const fetchMock = stubApi({
      ...base(),
      [IMPORT]: () => json(report),
      "PUT /profiles/1/resources/invoices": () => json(storedFixture()),
      "PUT /profiles/1/resources/products": () => {
        productCalls += 1;
        return productCalls === 1
          ? json({ error: "validation_error", detail: "get endpoint path must contain {id}" }, 422)
          : json(storedFixture());
      },
    });
    await renderImport();
    await analyseUrl();
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar invoices" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "Seleccionar products" }));
    await userEvent.click(screen.getByRole("button", { name: "Guardar seleccionados (2)" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(/Guardados: 1/);
    expect(alert).toHaveTextContent("products");
    expect(screen.getByText("invoices").closest("tr")).toHaveTextContent("Guardado");
    await userEvent.click(screen.getByRole("button", { name: "Guardar seleccionados (1)" }));
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
    const invoicePuts = fetchMock.mock.calls.filter(
      ([url, init]) => init?.method === "PUT" && url.endsWith("/invoices"),
    );
    expect(invoicePuts).toHaveLength(1);
  });
});
