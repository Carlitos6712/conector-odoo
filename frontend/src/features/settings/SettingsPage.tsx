import { useTranslation } from "react-i18next";
import { useSession } from "@/auth/useSession";
import { AboutSection } from "@/features/settings/AboutSection";
import { AccountSection } from "@/features/settings/AccountSection";
import { PreferencesSection } from "@/features/settings/PreferencesSection";
import { UsersSection } from "@/features/settings/UsersSection";

export function SettingsPage() {
  const { t } = useTranslation();
  const { isAdmin } = useSession();
  return (
    <section className="flex max-w-4xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">{t("settings.title")}</h1>
      <AccountSection />
      <PreferencesSection />
      {isAdmin && <UsersSection />}
      <AboutSection />
    </section>
  );
}
