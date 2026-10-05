import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Route, Routes } from "react-router-dom";
import { MappingVersionsPage } from "@/features/mappings/MappingVersionsPage";
import { mappingDocFixture, storedMappingFixture } from "@/features/mappings/fixtures";
import { json, renderApp, sessionBody, stubApi, type Role } from "@/test/utils";

afterEach(() => vi.unstubAllGlobals());

const older = mappingDocFixture({ rules: [] });
const versions = [
  storedMappingFixture({ version: 3 }),
  storedMappingFixture({ version: 2, definition: older }),
  storedMappingFixture({ version: 1, definition: older }),
];

function routes(role: Role = "admin") {
  return {
    "GET /auth/me": () => json(sessionBody(role)),
    "GET /mappings/clients-to-partner/versions": () => json({ items: versions }),
  };
}

const page = () =>
  renderApp(
    <Routes>
      <Route path="/mappings/:name/versions" element={<MappingVersionsPage />} />
    </Routes>,
    "/mappings/clients-to-partner/versions",
  );

describe("MappingVersionsPage", () => {
  it("lists versions newest first and marks the latest", async () => {
    stubApi(routes());
    await page();
    const rows = await screen.findAllByRole("row");
    expect(within(rows[1]!).getByText("v3")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Última")).toBeInTheDocument();
    expect(within(rows[3]!).getByText("v1")).toBeInTheDocument();
  });

  it("shows an older version read-only as JSON", async () => {
    stubApi(routes());
    await page();
    await userEvent.click(await screen.findByRole("button", { name: "Ver v2" }));
    const region = await screen.findByRole("region", { name: "Definición de la v2" });
    expect(region).toHaveTextContent('"source_resource": "clients"');
    expect(within(region).queryByRole("textbox")).not.toBeInTheDocument();
  });

  it("restores an older version as a new one", async () => {
    const mock = stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json({ mapping: storedMappingFixture({ version: 4 }), created: true, warnings: [] }),
    });
    await page();
    await userEvent.click(await screen.findByRole("button", { name: "Restaurar v2" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Se ha creado la versión 4");
    const call = mock.mock.calls.find(([, init]) => init?.method === "PUT")!;
    expect(JSON.parse(String(call[1]!.body))).toEqual({ definition: older });
  });

  it("reports when the restored version equals the latest", async () => {
    stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json({ mapping: storedMappingFixture({ version: 3 }), created: false, warnings: [] }),
    });
    await page();
    await userEvent.click(await screen.findByRole("button", { name: "Restaurar v2" }));
    expect(await screen.findByRole("status")).toHaveTextContent("ya coincide con la versión 3");
  });

  it("shows backend issues when the restore is rejected", async () => {
    stubApi({
      ...routes(),
      "PUT /mappings/clients-to-partner": () =>
        json(
          {
            error: "validation_error",
            detail: "x",
            issues: [{ path: "rules[0].target", severity: "error", message: "duplicate target" }],
          },
          422,
        ),
    });
    await page();
    await userEvent.click(await screen.findByRole("button", { name: "Restaurar v2" }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("rules[0].target");
    expect(alert).toHaveTextContent("duplicate target");
  });

  it("hides restore from operators and the latest version", async () => {
    stubApi(routes("operator"));
    await page();
    await screen.findByRole("button", { name: "Ver v2" });
    expect(screen.queryByRole("button", { name: /Restaurar/ })).not.toBeInTheDocument();
  });
});
