import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nextProvider } from "react-i18next";
import { Pagination } from "@/components/ui/pagination";
import { createI18n } from "@/i18n";

async function setup(props: { page: number; hasNext: boolean }) {
  const onPageChange = vi.fn();
  const i18n = await createI18n("es");
  render(
    <I18nextProvider i18n={i18n}>
      <Pagination {...props} onPageChange={onPageChange} />
    </I18nextProvider>,
  );
  return onPageChange;
}

describe("Pagination", () => {
  it("is a labelled navigation that names the current page", async () => {
    await setup({ page: 2, hasNext: true });
    const nav = screen.getByRole("navigation", { name: "Paginación" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByText("Página 2")).toHaveAttribute("aria-current", "page");
  });

  it("goes to the previous and next pages", async () => {
    const onPageChange = await setup({ page: 2, hasNext: true });
    await userEvent.click(screen.getByRole("button", { name: "Anterior" }));
    expect(onPageChange).toHaveBeenLastCalledWith(1);
    await userEvent.click(screen.getByRole("button", { name: "Siguiente" }));
    expect(onPageChange).toHaveBeenLastCalledWith(3);
  });

  it("disables previous on the first page and next on the last", async () => {
    await setup({ page: 1, hasNext: false });
    expect(screen.getByRole("button", { name: "Anterior" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Siguiente" })).toBeDisabled();
  });
});
