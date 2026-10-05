import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useToast } from "@/components/ui/toast";
import { renderApp } from "@/test/utils";

function Demo({ tone = "success" as "success" | "error" }) {
  const { toast } = useToast();
  return (
    <button
      onClick={() =>
        toast({ tone, message: "Ejecución #5 iniciada", action: { label: "Ver", to: "/runs/5" } })
      }
    >
      lanzar
    </button>
  );
}

describe("toast", () => {
  afterEach(() => vi.useRealTimers());

  it("announces a success politely and offers its link", async () => {
    await renderApp(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: "lanzar" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Ejecución #5 iniciada");
    expect(screen.getByRole("link", { name: "Ver" })).toHaveAttribute("href", "/runs/5");
  });

  it("announces an error assertively", async () => {
    await renderApp(<Demo tone="error" />);
    await userEvent.click(screen.getByRole("button", { name: "lanzar" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Ejecución #5 iniciada");
  });

  it("can be dismissed", async () => {
    await renderApp(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: "lanzar" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cerrar notificación" }));
    expect(screen.queryByText("Ejecución #5 iniciada")).not.toBeInTheDocument();
  });

  it("disappears by itself", async () => {
    await renderApp(<Demo />);
    vi.useFakeTimers({ shouldAdvanceTime: true });
    await userEvent.click(screen.getByRole("button", { name: "lanzar" }));
    expect(await screen.findByText("Ejecución #5 iniciada")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(9000));
    expect(screen.queryByText("Ejecución #5 iniciada")).not.toBeInTheDocument();
  });

  it("is a no-op without a provider", async () => {
    render(<Demo />);
    await userEvent.click(screen.getByRole("button", { name: "lanzar" }));
    expect(screen.queryByText("Ejecución #5 iniciada")).not.toBeInTheDocument();
  });
});
