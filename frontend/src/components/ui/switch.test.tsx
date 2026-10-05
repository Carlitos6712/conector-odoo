import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Switch } from "@/components/ui/switch";

describe("Switch", () => {
  it("exposes its state to assistive technology", () => {
    render(<Switch checked aria-label="Activa" onCheckedChange={() => {}} />);
    expect(screen.getByRole("switch", { name: "Activa" })).toHaveAttribute("aria-checked", "true");
  });

  it("asks for the opposite state when clicked or toggled with the keyboard", async () => {
    const onChange = vi.fn();
    render(<Switch checked={false} aria-label="Activa" onCheckedChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenLastCalledWith(true);
    screen.getByRole("switch").focus();
    await userEvent.keyboard(" ");
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("does nothing while disabled", async () => {
    const onChange = vi.fn();
    render(<Switch checked disabled aria-label="Activa" onCheckedChange={onChange} />);
    await userEvent.click(screen.getByRole("switch"));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("switch")).toBeDisabled();
  });
});
