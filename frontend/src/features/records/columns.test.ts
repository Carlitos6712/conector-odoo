import {
  allColumns,
  buildPatch,
  editableFields,
  initialForm,
  parseFieldErrors,
  pickColumns,
  recordLabel,
} from "@/features/records/columns";
import { pageFixture, partnerSchema } from "@/features/records/fixtures";

describe("pickColumns", () => {
  it("prefers name, email, vat, city and ref when the schema has them", () => {
    expect(pickColumns(partnerSchema).map((f) => f.name)).toEqual(["name", "email", "city"]);
  });

  it("falls back to the first simple fields when no preferred one exists", () => {
    const schema = {
      ...partnerSchema,
      fields: partnerSchema.fields.filter((f) => !["name", "email", "city"].includes(f.name)),
    };
    const names = pickColumns(schema).map((f) => f.name);
    expect(names).toEqual(["active", "write_date"]);
  });
});

describe("recordLabel", () => {
  it("uses the name, then display_name, then the id", () => {
    expect(recordLabel({ id: 1, fields: { name: "Ada" } })).toBe("Ada");
    expect(recordLabel({ id: 1, fields: { name: false, display_name: "Ada D" } })).toBe("Ada D");
    expect(recordLabel({ id: 1, fields: {} })).toBe("#1");
  });
});

describe("editableFields", () => {
  it("lists writable simple fields and skips readonly, id and relations", () => {
    const names = editableFields(partnerSchema, pageFixture().items[0]!).map((f) => f.name);
    expect(names).toEqual(["name", "email", "city", "active"]);
  });
});

describe("buildPatch", () => {
  const record = pageFixture().items[1]!;
  const specs = editableFields(partnerSchema, record);

  it("starts from the record values, false text becoming empty", () => {
    expect(initialForm(specs, record)).toEqual({
      name: "Alan Turing",
      email: "",
      city: "",
      active: true,
    });
  });

  it("sends only the fields that changed", () => {
    const form = { ...initialForm(specs, record), city: "Wilmslow" };
    expect(buildPatch(specs, record, form)).toEqual({ city: "Wilmslow" });
  });

  it("is empty when nothing changed", () => {
    expect(buildPatch(specs, record, initialForm(specs, record))).toEqual({});
  });

  it("sends booleans as booleans and clears numbers to null", () => {
    const schema = {
      ...partnerSchema,
      fields: [
        ...partnerSchema.fields,
        {
          name: "credit",
          type: "float",
          required: false,
          readonly: false,
          label: null,
          choices: null,
          relation: null,
        },
      ],
    };
    const rec = { id: 1, fields: { name: "A", active: true, credit: 2.5 } };
    const s = editableFields(schema, rec);
    const form = { ...initialForm(s, rec), active: false, credit: "" };
    expect(buildPatch(s, rec, form)).toEqual({ active: false, credit: null });
    expect(buildPatch(s, rec, { ...initialForm(s, rec), credit: "4" })).toEqual({ credit: 4 });
  });
});

describe("parseFieldErrors", () => {
  it("maps 'field: why' segments of known fields", () => {
    const out = parseFieldErrors("cannot edit res.partner: email: bad format; zip: nope", [
      "email",
      "city",
    ]);
    expect(out.fieldErrors).toEqual({ email: "bad format" });
    expect(out.general).toBeNull();
  });

  it("keeps unmatched text as a general message", () => {
    const out = parseFieldErrors("Odoo said no", ["email"]);
    expect(out).toEqual({ fieldErrors: {}, general: "Odoo said no" });
  });
});

describe("allColumns", () => {
  it("lists every schema field but the id, then keys only present in the records", () => {
    const names = allColumns(partnerSchema, [
      { id: 1, fields: { name: "x", extra: 1 } },
      { id: 2, fields: { other: { a: 1 }, extra: 2 } },
    ]).map((f) => f.name);
    expect(names).toEqual([
      "name",
      "email",
      "city",
      "active",
      "write_date",
      "country_id",
      "extra",
      "other",
    ]);
  });
});
