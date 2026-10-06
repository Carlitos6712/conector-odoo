import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { odooProfileFixture, profileFixture } from "@/features/connections/fixtures";
import { configFixture, previewFixture, storedFixture } from "@/features/resources/fixtures";
import { ResourceEditorPage } from "@/features/resources/ResourceEditorPage";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const base = (role: Role = "admin") => ({
  "GET /auth/me": () => json(sessionBody(role)),
  "GET /profiles": () =>
    json({ items: [profileFixture(), profileFixture({ id: 3, name: "ERP" }), odooProfileFixture] }),
  "GET /profiles/1/resources": () => json({ items: [storedFixture()], invalid: [] }),
});

async function renderEditor(route: string) {
  return renderApp(
    <Routes>
      <Route path="/resources/new" element={<ResourceEditorPage />} />
      <Route path="/resources/:profileId/:name/edit" element={<ResourceEditorPage />} />
      <Route path="/resources" element={<p>LISTA DE RECURSOS</p>} />
    </Routes>,
    route,
  );
}

function savedBody(fetchMock: ReturnType<typeof stubApi>) {
  const call = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
  return JSON.parse(String(call?.[1]?.body)) as Record<string, unknown>;
}

describe("ResourceEditorPage (create)", () => {
  it("only offers REST connections and preselects the one in the URL", async () => {
    stubApi(base());
    await renderEditor("/resources/new?profile=3");
    const select = await screen.findByLabelText("Conexión");
    const options = within(select)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(options).toEqual(["Elige una conexión", "SUWE", "ERP"]);
    expect(select).toHaveValue("3");
  });

  it("shows only the parameters of the selected pagination strategy", async () => {
    stubApi(base());
    await renderEditor("/resources/new?profile=1");
    const strategy = await screen.findByLabelText("Estrategia de paginación");
    expect(strategy).toHaveValue("none");
    expect(screen.queryByLabelText("Parámetro de página")).not.toBeInTheDocument();
    expect(screen.getByText(/toda la lista en una sola respuesta/)).toBeInTheDocument();

    await userEvent.selectOptions(strategy, "Por páginas");
    expect(screen.getByLabelText("Parámetro de página")).toBeInTheDocument();
    expect(screen.getByLabelText("Parámetro de tamaño de página")).toBeInTheDocument();
    expect(screen.getByLabelText("Primera página")).toBeInTheDocument();
    expect(screen.getByLabelText(/Ruta del total de páginas/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Parámetro de desplazamiento")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Parámetro de cursor")).not.toBeInTheDocument();

    await userEvent.selectOptions(strategy, "Por desplazamiento");
    expect(screen.getByLabelText("Parámetro de desplazamiento")).toBeInTheDocument();
    expect(screen.getByLabelText("Parámetro de límite")).toBeInTheDocument();
    expect(screen.getByLabelText(/Ruta del total \(/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Parámetro de página")).not.toBeInTheDocument();

    await userEvent.selectOptions(strategy, "Por cursor");
    expect(screen.getByLabelText("Parámetro de cursor")).toBeInTheDocument();
    expect(screen.getByLabelText("Ruta del siguiente cursor")).toBeInTheDocument();
    expect(screen.getByLabelText("Parámetro de límite")).toBeInTheDocument();
    expect(screen.queryByLabelText("Parámetro de desplazamiento")).not.toBeInTheDocument();
  });

  it("validates inline and sends nothing while the form is invalid", async () => {
    const fetchMock = stubApi(base());
    await renderEditor("/resources/new?profile=1");
    await userEvent.type(await screen.findByLabelText("Nombre"), "bad name");
    await userEvent.type(screen.getByLabelText(/Endpoint de lista/), "clients");
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByText(/solo puede contener letras/)).toBeInTheDocument();
    expect(screen.getByText(/Debe empezar por «\/»/)).toBeInTheDocument();
    expect(screen.getByLabelText("Nombre")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("requires the next-cursor path for the cursor strategy", async () => {
    stubApi(base());
    await renderEditor("/resources/new?profile=1");
    await userEvent.type(await screen.findByLabelText("Nombre"), "clients");
    await userEvent.type(screen.getByLabelText(/Endpoint de lista/), "/clients");
    await userEvent.selectOptions(screen.getByLabelText("Estrategia de paginación"), "Por cursor");
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByLabelText("Ruta del siguiente cursor")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });

  it("refuses a name that already exists in the connection", async () => {
    const fetchMock = stubApi(base());
    await renderEditor("/resources/new?profile=1");
    await userEvent.type(await screen.findByLabelText("Nombre"), "clients");
    await userEvent.type(screen.getByLabelText(/Endpoint de lista/), "/clients");
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByText(/Ya existe un recurso con este nombre/)).toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "PUT")).toBe(false);
  });

  it("saves a page-paginated resource and goes back to the list", async () => {
    const fetchMock = stubApi({
      ...base(),
      "PUT /profiles/1/resources/orders": () => json(storedFixture(), 200),
    });
    await renderEditor("/resources/new?profile=1");
    await userEvent.type(await screen.findByLabelText("Nombre"), "orders");
    await userEvent.type(screen.getByLabelText(/Endpoint de lista/), "/orders");
    await userEvent.clear(screen.getByLabelText("Campo identificador"));
    await userEvent.type(screen.getByLabelText("Campo identificador"), "uuid");
    await userEvent.type(screen.getByLabelText(/Ruta de la lista/), "items");
    await userEvent.selectOptions(screen.getByLabelText("Estrategia de paginación"), "Por páginas");
    await userEvent.type(screen.getByLabelText(/Ruta del total de páginas/), "total_pages");
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
    const body = savedBody(fetchMock) as {
      list_endpoint: unknown;
      id_field: string;
      items_path: string;
      source: string;
      pagination: Record<string, unknown>;
    };
    expect(body.list_endpoint).toEqual({ method: "GET", path: "/orders" });
    expect(body.id_field).toBe("uuid");
    expect(body.items_path).toBe("items");
    expect(body.source).toBe("manual");
    expect(body.pagination).toMatchObject({
      strategy: "page",
      page_param: "page",
      size_param: "page_size",
      first_page: 1,
      total_pages_path: "total_pages",
    });
  });

  it("shows the validation answer of the server and the rate limit", async () => {
    let status = 422;
    stubApi({
      ...base(),
      "PUT /profiles/1/resources/orders": () =>
        status === 422
          ? json({ error: "validation_error", detail: "body.id_field: Field required" }, 422)
          : json({ error: "rate_limited", detail: "" }, 429, { "Retry-After": "9" }),
    });
    await renderEditor("/resources/new?profile=1");
    await userEvent.type(await screen.findByLabelText("Nombre"), "orders");
    await userEvent.type(screen.getByLabelText(/Endpoint de lista/), "/orders");
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/Algunos datos no son válidos/);
    expect(screen.getByLabelText("Campo identificador")).toHaveAttribute("aria-invalid", "true");
    status = 429;
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/9 segundos/));
  });

  it("sends operators back to the list", async () => {
    stubApi(base("operator"));
    await renderEditor("/resources/new?profile=1");
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
  });
});

describe("ResourceEditorPage (edit)", () => {
  const routes = () => ({
    ...base(),
    "GET /profiles/1/resources/clients": () =>
      json(
        storedFixture({
          source: "openapi",
          config: {
            schema_fields: [
              {
                name: "uuid",
                type: "string",
                required: true,
                readonly: true,
                label: null,
                choices: null,
                relation: null,
              },
            ],
            filter_param_map: { status: "state" },
            pagination: { ...configFixture().pagination, strategy: "none" },
          },
        }),
      ),
  });

  it("loads the saved resource and locks its identity", async () => {
    stubApi(routes());
    await renderEditor("/resources/1/clients/edit");
    expect(await screen.findByLabelText("Nombre")).toHaveValue("clients");
    expect(screen.getByLabelText("Nombre")).toBeDisabled();
    expect(screen.getByLabelText("Conexión")).toBeDisabled();
    expect(screen.getByLabelText(/Endpoint de lista/)).toHaveValue("/organization/clients");
    expect(screen.getByLabelText("Campo identificador")).toHaveValue("uuid");
    expect(screen.getByLabelText(/Filtros/)).toHaveValue("status=state");
  });

  it("explains that an imported resource without pagination must be configured by hand", async () => {
    stubApi(routes());
    await renderEditor("/resources/1/clients/edit");
    expect(await screen.findByText(/no describe cómo se pagina/)).toBeInTheDocument();
  });

  it("keeps the inferred schema when saving", async () => {
    const fetchMock = stubApi({
      ...routes(),
      "PUT /profiles/1/resources/clients": () => json(storedFixture()),
    });
    await renderEditor("/resources/1/clients/edit");
    await userEvent.selectOptions(
      await screen.findByLabelText("Estrategia de paginación"),
      "Por páginas",
    );
    await userEvent.click(screen.getByRole("button", { name: "Guardar recurso" }));
    expect(await screen.findByText("LISTA DE RECURSOS")).toBeInTheDocument();
    const body = savedBody(fetchMock) as {
      schema_fields: unknown[];
      source: string;
      filter_param_map: unknown;
    };
    expect(body.schema_fields).toHaveLength(1);
    expect(body.source).toBe("openapi");
    expect(body.filter_param_map).toEqual({ status: "state" });
  });

  it("runs the preview of the saved configuration on demand", async () => {
    const fetchMock = stubApi({
      ...routes(),
      "POST /profiles/1/resources/clients/preview?limit=5": () => json(previewFixture),
    });
    await renderEditor("/resources/1/clients/edit");
    await screen.findByLabelText("Nombre");
    expect(fetchMock.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Probar vista previa" }));
    expect(await screen.findByText("Acme")).toBeInTheDocument();
  });

  it("reports a resource that no longer exists", async () => {
    stubApi({
      ...base(),
      "GET /profiles/1/resources/clients": () => json({ error: "not_found", detail: "" }, 404),
    });
    await renderEditor("/resources/1/clients/edit");
    expect(await screen.findByRole("alert")).toHaveTextContent(/ya no existe/);
  });
});
