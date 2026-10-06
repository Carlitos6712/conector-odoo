import { fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { CronEditor } from "@/features/jobs/CronEditor";
import { renderApp } from "@/test/utils";

function Harness({ initial, error }: { initial: string; error?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <CronEditor value={value} error={error} onChange={setValue} />
      <p data-testid="cron">{value}</p>
    </>
  );
}

const cron = () => screen.getByTestId("cron").textContent;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-01-01T10:07:30Z") });
});
afterEach(() => vi.useRealTimers());

describe("CronEditor", () => {
  it("describes the schedule in words and lists the next three fire times in UTC", async () => {
    await renderApp(<Harness initial="30 9 * * *" />);
    expect(screen.getByText("Todos los días a las 09:30 UTC")).toBeInTheDocument();
    const fires = screen.getByRole("list", { name: "Próximas ejecuciones (UTC)" });
    expect(fires).toHaveTextContent("2026-01-02 09:30 UTC");
    expect(fires).toHaveTextContent("2026-01-03 09:30 UTC");
    expect(fires).toHaveTextContent("2026-01-04 09:30 UTC");
  });

  it("recognises a preset from the expression", async () => {
    await renderApp(<Harness initial="0 8 * * 1,3" />);
    expect(screen.getByRole("radio", { name: "Cada semana" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Lun" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Mié" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Mar" })).not.toBeChecked();
  });

  it("opens the advanced editor for anything that is not a preset", async () => {
    await renderApp(<Harness initial="*/5 * * * *" />);
    expect(screen.getByRole("radio", { name: "Avanzado" })).toBeChecked();
    expect(screen.getByLabelText("Expresión cron")).toHaveValue("*/5 * * * *");
    expect(screen.getByText("Cada 5 minutos")).toBeInTheDocument();
  });

  it("builds a weekly schedule keeping the time", async () => {
    await renderApp(<Harness initial="30 9 * * *" />);
    await userEvent.click(screen.getByRole("radio", { name: "Cada semana" }));
    expect(cron()).toBe("30 9 * * 1");
    await userEvent.click(screen.getByRole("checkbox", { name: "Mié" }));
    expect(cron()).toBe("30 9 * * 1,3");
    expect(screen.getByText("Los lunes y miércoles a las 09:30 UTC")).toBeInTheDocument();
  });

  it("builds an hourly schedule", async () => {
    await renderApp(<Harness initial="30 9 * * *" />);
    await userEvent.click(screen.getByRole("radio", { name: "Cada hora" }));
    expect(cron()).toBe("30 * * * *");
    expect(screen.queryByLabelText("Hora")).not.toBeInTheDocument();
  });

  it("edits the hour and minute of a daily schedule without losing a half-typed value", async () => {
    await renderApp(<Harness initial="30 9 * * *" />);
    const hour = screen.getByLabelText("Hora");
    await userEvent.clear(hour);
    expect(cron()).toBe("30 9 * * *");
    await userEvent.type(hour, "14");
    expect(cron()).toBe("30 14 * * *");
    fireEvent.change(screen.getByLabelText("Minuto"), { target: { value: "5" } });
    expect(cron()).toBe("5 14 * * *");
  });

  it("keeps the expression when switching to the advanced editor", async () => {
    await renderApp(<Harness initial="30 9 * * *" />);
    await userEvent.click(screen.getByRole("radio", { name: "Avanzado" }));
    expect(screen.getByLabelText("Expresión cron")).toHaveValue("30 9 * * *");
  });

  it("validates the advanced expression while typing", async () => {
    await renderApp(<Harness initial="*/5 * * * *" />);
    fireEvent.change(screen.getByLabelText("Expresión cron"), { target: { value: "61 * * * *" } });
    expect(screen.getByRole("alert")).toHaveTextContent("Valor fuera de rango.");
    expect(screen.getByLabelText("Expresión cron")).toBeInvalid();
    expect(
      screen.queryByRole("list", { name: "Próximas ejecuciones (UTC)" }),
    ).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("Expresión cron"), { target: { value: "* * *" } });
    expect(screen.getByRole("alert")).toHaveTextContent(/necesita 5 campos/);
  });

  it("warns about an expression that never fires", async () => {
    await renderApp(<Harness initial="0 0 31 2 *" />);
    expect(screen.getByRole("alert")).toHaveTextContent(/no se ejecuta nunca/);
  });

  it("shows an error handed down by the form", async () => {
    await renderApp(<Harness initial="30 9 * * *" error="Error del servidor" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Error del servidor");
  });
});
