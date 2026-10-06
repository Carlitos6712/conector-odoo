import { useTranslation } from "react-i18next";
import { EmptyState } from "@/components/EmptyState";
import type { NavItem } from "@/nav";

/** Stand-in for sections built in later tasks (F2-F8). */
export function PlaceholderPage({ section }: { section: NavItem["key"] }) {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">{t(`nav.${section}`)}</h1>
      <EmptyState message={t("placeholder.comingSoon")} />
    </section>
  );
}
