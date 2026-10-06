import { expect, test } from "@playwright/test";
import { ADMIN_PASSWORD, ADMIN_USER, login, logout, requireSuweFake, signIn } from "./support";

const OPERATOR = "e2e-operator";
const OPERATOR_PASSWORD = "operator-password-12";

test("a wrong password shows the error and does not open a session", async ({ page }) => {
  await login(page, "nobody-here", "definitely-wrong-password");
  await expect(page.getByText("Usuario o contraseña incorrectos.")).toBeVisible();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("navigation", { name: "Navegación principal" })).toHaveCount(0);
});

// Runs after 01-sync-flow (one worker, alphabetical file order): it looks at the connections,
// the job and the runs that flow created, so it is skipped together with it.
test.describe("operator", () => {
  requireSuweFake();
  test("an operator created by the admin is read-only", async ({ page }) => {
    await test.step("the admin creates the operator", async () => {
      await signIn(page, ADMIN_USER, ADMIN_PASSWORD);
      await page.goto("/settings");
      await page.getByRole("button", { name: "Nuevo usuario" }).click();
      const dialog = page.getByRole("dialog", { name: "Nuevo usuario" });
      await dialog.getByLabel("Usuario").fill(OPERATOR);
      await dialog.getByLabel("Contraseña inicial").fill(OPERATOR_PASSWORD);
      await dialog.getByLabel("Rol").selectOption({ label: "Operador" });
      await dialog.getByRole("button", { name: "Crear usuario" }).click();
      await expect(page.getByRole("row", { name: new RegExp(OPERATOR) })).toBeVisible();
      await logout(page);
    });

    await test.step("the operator sees the read-only banner and no mutating controls", async () => {
      await signIn(page, OPERATOR, OPERATOR_PASSWORD);
      await expect(
        page.getByText("Modo solo lectura: tu rol no permite modificar datos."),
      ).toBeVisible();

      await page.goto("/connections");
      await expect(page.getByRole("heading", { name: "Conexiones" })).toBeVisible();
      await expect(page.getByRole("row", { name: /SUWE fake/ })).toBeVisible();
      await expect(page.getByRole("link", { name: "Nueva conexión" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: "Nueva conexión" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Eliminar / })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Probar / })).toHaveCount(0);

      await page.goto("/jobs");
      await expect(page.getByRole("row", { name: /Sync clients/ })).toBeVisible();
      await expect(page.getByRole("link", { name: "Nueva tarea" })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /ahora$/ })).toHaveCount(0);
      await expect(page.getByRole("button", { name: /^Simular / })).toHaveCount(0);

      await page.goto("/runs");
      await expect(page.getByRole("row", { name: /Sync clients/ }).first()).toBeVisible();

      await page.goto("/settings");
      await expect(page.getByRole("button", { name: "Nuevo usuario" })).toHaveCount(0);
      await expect(page.getByRole("region", { name: "Mi cuenta" })).toBeVisible();
      await expect(page.getByRole("region", { name: "Usuarios" })).toHaveCount(0);
    });
  });
});
