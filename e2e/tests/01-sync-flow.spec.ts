import { expect, test, type APIRequestContext, type Locator, type Page } from "@playwright/test";
import {
  ADMIN_PASSWORD,
  ADMIN_USER,
  ODOO_DB,
  ODOO_KEY,
  ODOO_LOGIN,
  ODOO_URL,
  SUWE_API,
  login,
  odooCall,
  requireSuweFake,
  suweClientCount,
  suweClientIds,
} from "./support";

requireSuweFake();

const SUWE_CONNECTION = "SUWE fake";
const ODOO_CONNECTION = "Odoo fake";
const RESOURCE = "clients";
const MAPPING = "clients-to-partner";
const JOB = "Sync clients";

// source field -> res.partner field (checked with curl against the fake: no email on clients)
const RULES: Array<[source: string, target: string]> = [
  ["name", "name"],
  ["uuid", "ref"],
  ["tax_id", "vat"],
  ["city", "city"],
  ["address", "street"],
];

test("connect SUWE, map clients to res.partner, simulate, run, see it in history, run again", async ({
  page,
  request,
}) => {
  const total = await suweClientCount(request);
  expect(total).toBeGreaterThan(0);
  expect(await odooCall(request, "res.partner", "search_read", [[]], { fields: ["id"] })).toEqual(
    [],
  );

  await test.step("log in as the bootstrap admin", async () => {
    await login(page, ADMIN_USER, ADMIN_PASSWORD);
    await expect(page.getByRole("navigation", { name: "Navegación principal" })).toBeVisible();
    await expect(page.getByRole("complementary").getByText(ADMIN_USER)).toBeVisible();
  });

  await test.step("create the SUWE REST connection and pass the draft test", async () => {
    await page.goto("/connections/new");
    await page.getByLabel("API REST").check();
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByLabel("Nombre", { exact: true }).fill(SUWE_CONNECTION);
    await page.getByLabel("URL base").fill(`${SUWE_API}/api/v1`);
    await page.getByLabel("Tipo de autenticación").selectOption("bearer");
    await page.getByLabel("Token Bearer").fill("dummy-token-for-the-fake");
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByRole("button", { name: "Probar conexión" }).click();
    await expect(page.getByText("Conexión correcta")).toBeVisible();
    for (const step of ["url_valid", "reachable", "tls", "auth"]) {
      await expect(page.locator(`[data-step="${step}"]`)).toHaveAttribute("data-state", "ok");
    }
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByRole("button", { name: "Guardar conexión" }).click();
    await expect(page.getByRole("row", { name: new RegExp(SUWE_CONNECTION) })).toBeVisible();
  });

  await test.step("create the Odoo connection (fake Odoo)", async () => {
    await page.goto("/connections/new");
    await page.getByLabel("Odoo", { exact: true }).check();
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByLabel("Nombre", { exact: true }).fill(ODOO_CONNECTION);
    await page.getByLabel("URL base").fill(ODOO_URL);
    await page.getByLabel("Base de datos").fill(ODOO_DB);
    await page.getByLabel("Usuario de Odoo").fill(ODOO_LOGIN);
    await page.getByLabel("Clave de API").fill(ODOO_KEY);
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByRole("button", { name: "Probar conexión" }).click();
    await expect(page.getByText("Conexión correcta")).toBeVisible();
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByRole("button", { name: "Guardar conexión" }).click();
    await expect(page.getByRole("row", { name: new RegExp(ODOO_CONNECTION) })).toBeVisible();
  });

  await test.step("define the clients resource (pagination set by hand) and preview records", async () => {
    await page.goto("/resources/new");
    await page.getByLabel("Conexión").selectOption({ label: SUWE_CONNECTION });
    await page.getByLabel("Nombre", { exact: true }).fill(RESOURCE);
    await page.getByLabel("Endpoint de lista (GET)").fill("/organization/clients");
    await page.getByLabel("Campo identificador").fill("uuid");
    await page.getByLabel("Ruta de la lista en la respuesta").fill("items");
    await page.getByLabel("Estrategia de paginación").selectOption("page");
    await page.getByLabel("Ruta del total de páginas (opcional)").fill("total_pages");
    await page.getByRole("button", { name: "Guardar recurso" }).click();
    await expect(page).toHaveURL(/\/resources/);
    await page.getByRole("button", { name: `Vista previa de ${RESOURCE}` }).click();
    await expect(page.getByRole("heading", { name: `Vista previa de ${RESOURCE}` })).toBeVisible();
    await expect(page.getByText("Supermercados Aurora").first()).toBeVisible();
  });

  await test.step("map clients to res.partner and see the dry-run output", async () => {
    await page.goto("/mappings/new");
    await page.getByLabel("Nombre", { exact: true }).fill(MAPPING);
    const source = page.getByRole("group", { name: "Origen", exact: true });
    await source.getByLabel("Conexión").selectOption({ label: SUWE_CONNECTION });
    await source.getByLabel("Recurso").selectOption(RESOURCE);
    const target = page.getByRole("group", { name: "Destino", exact: true });
    await target.getByLabel("Conexión").selectOption({ label: ODOO_CONNECTION });
    await target.getByLabel("Modelo de Odoo").fill("res.partner");
    await target.getByLabel("Modelo de Odoo").blur();
    for (const [index, [from, to]] of RULES.entries()) {
      await page.getByRole("button", { name: "Añadir regla" }).click();
      const rule = page.getByRole("group", { name: `Regla ${index + 1}` });
      await rule.getByLabel("Campo de destino").fill(to);
      await rule.getByLabel("Campo de origen").fill(from);
    }
    await page.getByRole("button", { name: "Ejecutar prueba" }).click();
    await expect(page.getByText("Correcto").first()).toBeVisible();
    await expect(page.getByText(/5 correctos, 0 con errores/)).toBeVisible();
    await page.getByRole("button", { name: "Guardar nueva versión" }).click();
    await expect(page.getByText("Versión 1 guardada.")).toBeVisible();
  });

  await test.step("create a manual job and simulate it with 'Guardar y simular'", async () => {
    await page.goto("/jobs/new");
    await page.getByLabel("Nombre", { exact: true }).fill(JOB);
    await page.getByRole("button", { name: "Siguiente" }).click();
    const jobSource = page.getByRole("group", { name: "Origen", exact: true });
    await jobSource.getByLabel("Conexión").selectOption({ label: SUWE_CONNECTION });
    await jobSource.getByLabel("Recurso").selectOption(RESOURCE);
    const jobTarget = page.getByRole("group", { name: "Destino", exact: true });
    await jobTarget.getByLabel("Conexión").selectOption({ label: ODOO_CONNECTION });
    await jobTarget.getByLabel("Modelo de Odoo").fill("res.partner");
    await jobTarget.getByLabel("Modelo de Odoo").blur();
    await page.getByLabel("Mapeo", { exact: true }).selectOption(MAPPING);
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByLabel("Buscar por un campo del destino").check();
    await page.getByRole("combobox", { name: "Campo del destino" }).fill("ref");
    await page.getByRole("button", { name: "Siguiente" }).click();
    await page.getByRole("button", { name: "Siguiente" }).click(); // manual trigger is the default
    await page.getByRole("button", { name: "Guardar y simular" }).click();
    const simulation = page.getByRole("region", { name: "Resultado de la simulación" });
    await expect(simulation).toBeVisible();
    await expectCounter(simulation, "Procesados", total);
    await expectCounter(simulation, "Creados", total);
    await expectCounter(simulation, "Fallidos", 0);
    // A simulation writes nothing.
    expect(await odooCall(request, "res.partner", "search_read", [[]], { fields: ["id"] })).toEqual(
      [],
    );
  });

  await test.step("run the job now and wait for it to complete", async () => {
    await runJobNow(page);
    await expect(page.getByRole("heading", { name: /^Ejecución #\d+$/ })).toBeVisible();
    await expect(page.getByText("Correcta").first()).toBeVisible({ timeout: 30_000 });
  });

  await test.step("the run detail counters match the live client count", async () => {
    const detail = page.getByRole("region", { name: "Progreso" });
    await expectCounter(detail, "Procesados", total);
    await expectCounter(detail, "Creados", total);
    await expectCounter(detail, "Actualizados", 0);
    await expectCounter(detail, "Fallidos", 0);
    await expectCounter(detail, "Conflictos", 0);
  });

  await test.step("the run is listed in the history as completed", async () => {
    await page.goto("/runs");
    const row = page.getByRole("row", { name: new RegExp(JOB) }).first();
    await expect(row).toContainText("Correcta");
    await expect(row).toContainText(`${total} creados`);
  });

  await test.step("every SUWE client exists in Odoo exactly once", async () => {
    const expected = await suweClientIds(request);
    expect(expected).toHaveLength(total);
    await expect
      .poll(async () => (await partnerRefs(request)).sort())
      .toEqual([...expected].sort());
    const [first] = await odooCall<Array<{ name: string; city: string | false }>>(
      request,
      "res.partner",
      "search_read",
      [[["ref", "=", expected[0]]]],
      { fields: ["name", "city"] },
    );
    expect(first?.name).toBeTruthy();
  });

  await test.step("running again is idempotent: nothing is created", async () => {
    await runJobNow(page);
    await expect(page.getByText("Correcta").first()).toBeVisible({ timeout: 30_000 });
    const detail = page.getByRole("region", { name: "Progreso" });
    await expectCounter(detail, "Procesados", total);
    await expectCounter(detail, "Creados", 0);
    await expectCounter(detail, "Fallidos", 0);
    expect(await partnerRefs(request)).toHaveLength(total);
  });
});

async function runJobNow(page: Page): Promise<void> {
  await page.goto("/jobs");
  await page.getByRole("button", { name: `Ejecutar ${JOB} ahora` }).click();
  await page.getByRole("button", { name: "Ejecutar", exact: true }).click();
  await page.getByRole("link", { name: "Ver ejecución" }).first().click();
}

async function expectCounter(scope: Locator, label: string, value: number): Promise<void> {
  const term = scope.locator("dt", { hasText: new RegExp(`^${label}$`) });
  await expect(term.locator("xpath=following-sibling::dd")).toHaveText(String(value));
}

async function partnerRefs(request: APIRequestContext): Promise<string[]> {
  const rows = await odooCall<Array<{ ref: string }>>(request, "res.partner", "search_read", [[]], {
    fields: ["ref"],
  });
  return rows.map((row) => row.ref);
}
