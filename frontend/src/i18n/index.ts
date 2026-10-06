import { createInstance, type i18n as I18nInstance, type Resource } from "i18next";
import { initReactI18next } from "react-i18next";
import { en } from "@/i18n/en";
import { es } from "@/i18n/es";

export const DEFAULT_LANGUAGE = "es";

export const resources = { es: { translation: es }, en: { translation: en } };

/** Builds an isolated i18n instance (Spanish default, Spanish as the fallback for gaps). */
export async function createI18n(
  language: string = DEFAULT_LANGUAGE,
  customResources: Resource = resources,
): Promise<I18nInstance> {
  const instance = createInstance();
  await instance.use(initReactI18next).init({
    resources: customResources,
    lng: language,
    fallbackLng: DEFAULT_LANGUAGE,
    interpolation: { escapeValue: false }, // React already escapes
    returnNull: false,
  });
  return instance;
}
