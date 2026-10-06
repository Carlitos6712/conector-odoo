import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { CheckboxGroup } from "@/components/ui/checkbox-group";
import { RadioGroup } from "@/components/ui/radio-group";

const options = [
  { value: "a", label: "Alfa", description: "La primera" },
  { value: "b", label: "Beta" },
  { value: "c", label: "Gamma" },
];

function Radios({ initial = "a", disabled = false }) {
  const [value, setValue] = useState(initial);
  return (
    <RadioGroup
      legend="Letra"
      name="letter"
      value={value}
      options={options}
      disabled={disabled}
      onChange={setValue}
    />
  );
}

function Checks({ initial = ["b"], error }: { initial?: string[]; error?: string }) {
  const [values, setValues] = useState(initial);
  return (
    <>
      <CheckboxGroup
        legend="Letras"
        values={values}
        options={options}
        error={error}
        onChange={setValues}
      />
      <output>{values.join(",")}</output>
    </>
  );
}

describe("RadioGroup", () => {
  it("is a named group with the current option checked and its description linked", () => {
    render(<Radios />);
    const group = screen.getByRole("group", { name: "Letra" });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Alfa" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Alfa" })).toHaveAccessibleDescription("La primera");
  });

  it("selects on click and with the arrow keys", async () => {
    render(<Radios />);
    await userEvent.click(screen.getByRole("radio", { name: "Gamma" }));
    expect(screen.getByRole("radio", { name: "Gamma" })).toBeChecked();
    await userEvent.keyboard("{ArrowUp}");
    expect(screen.getByRole("radio", { name: "Beta" })).toBeChecked();
  });

  it("can be disabled as a whole", () => {
    render(<Radios disabled />);
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
  });
});

describe("CheckboxGroup", () => {
  it("reflects the selected values", () => {
    render(<Checks />);
    expect(screen.getByRole("group", { name: "Letras" })).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Beta" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Alfa" })).not.toBeChecked();
  });

  it("adds and removes values keeping the order of the options", async () => {
    render(<Checks initial={["c"]} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Alfa" }));
    expect(screen.getByRole("status")).toHaveTextContent("a,c");
    await userEvent.click(screen.getByRole("checkbox", { name: "Gamma" }));
    expect(screen.getByRole("status")).toHaveTextContent("a");
    await userEvent.click(screen.getByRole("checkbox", { name: "Beta" }));
    expect(screen.getByRole("status")).toHaveTextContent("a,b");
  });

  it("shows an error linked to the group", () => {
    render(<Checks error="Elige al menos uno" />);
    expect(screen.getByRole("group", { name: "Letras" })).toHaveAccessibleDescription(
      "Elige al menos uno",
    );
    expect(screen.getByText("Elige al menos uno")).toBeInTheDocument();
  });
});
