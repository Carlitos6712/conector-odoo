import type { RecordPage, RecordSchema } from "@/features/records/types";

/** Test fixtures for the records suites (never imported by app code). */
export const partnerSchema: RecordSchema = {
  name: "res.partner",
  label: "Contact",
  id_field: "id",
  fields: [
    {
      name: "id",
      type: "integer",
      required: false,
      readonly: true,
      label: "ID",
      choices: null,
      relation: null,
    },
    {
      name: "name",
      type: "char",
      required: true,
      readonly: false,
      label: "Nombre",
      choices: null,
      relation: null,
    },
    {
      name: "email",
      type: "char",
      required: false,
      readonly: false,
      label: "Correo",
      choices: null,
      relation: null,
    },
    {
      name: "city",
      type: "char",
      required: false,
      readonly: false,
      label: "Ciudad",
      choices: null,
      relation: null,
    },
    {
      name: "active",
      type: "boolean",
      required: false,
      readonly: false,
      label: "Activo",
      choices: null,
      relation: null,
    },
    {
      name: "write_date",
      type: "datetime",
      required: false,
      readonly: true,
      label: "Modificado",
      choices: null,
      relation: null,
    },
    {
      name: "country_id",
      type: "many2one",
      required: false,
      readonly: false,
      label: "País",
      choices: null,
      relation: "res.country",
    },
  ],
};

export function pageFixture(overrides: Partial<RecordPage> = {}): RecordPage {
  return {
    items: [
      {
        id: 7,
        fields: {
          name: "Ada Lovelace",
          email: "ada@example.com",
          city: "Londres",
          active: true,
          write_date: "2026-01-01",
          country_id: [3, "Reino Unido"],
        },
      },
      {
        id: 8,
        fields: {
          name: "Alan Turing",
          email: false,
          city: false,
          active: true,
          write_date: "2026-01-02",
          country_id: false,
        },
      },
    ],
    schema: partnerSchema,
    limit: 25,
    offset: 0,
    has_more: false,
    ...overrides,
  };
}
