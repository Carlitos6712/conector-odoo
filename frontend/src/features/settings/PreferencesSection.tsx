import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RadioGroup } from "@/components/ui/radio-group";
import { Select } from "@/components/ui/select";
import { Field } from "@/features/settings/Field";
import {
  LANGUAGES,
  readLanguage,
  readTheme,
  THEMES,
  writeLanguage,
  writeTheme,
  type Language,
  type Theme,
} from "@/features/settings/preferences";

/** Language and theme: per-browser, shown to every role. */
export function PreferencesSection() {
  const { t, i18n } = useTranslation();
  const [theme, setTheme] = useState<Theme>(readTheme);
  const language = LANGUAGES.find((l) => l === i18n.language) ?? readLanguage();

  function chooseLanguage(next: Language) {
    writeLanguage(next);
    void i18n.changeLanguage(next);
  }

  function chooseTheme(next: Theme) {
    writeTheme(next);
    setTheme(next);
  }

  return (
    <Card role="region" aria-labelledby="settings-preferences">
      <CardHeader>
        <CardTitle id="settings-preferences">{t("settings.preferences.title")}</CardTitle>
        <CardDescription>{t("settings.preferences.description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex max-w-sm flex-col gap-6">
        <Field label={t("settings.preferences.language")}>
          {(props) => (
            <Select
              {...props}
              value={language}
              onChange={(e) => chooseLanguage(e.target.value as Language)}
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>
                  {t(`settings.preferences.languages.${l}`)}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <RadioGroup
          legend={t("settings.preferences.theme")}
          name="theme"
          value={theme}
          onChange={(value) => chooseTheme(value as Theme)}
          options={THEMES.map((value) => ({
            value,
            label: t(`settings.preferences.themes.${value}`),
            description: t(`settings.preferences.themeDescriptions.${value}`),
          }))}
        />
      </CardContent>
    </Card>
  );
}
