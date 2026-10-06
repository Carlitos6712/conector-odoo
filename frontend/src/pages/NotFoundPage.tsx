import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col items-start gap-3">
      <h1 className="text-2xl font-semibold">{t("errors.notFoundTitle")}</h1>
      <Link className="underline" to="/">
        {t("common.backHome")}
      </Link>
    </section>
  );
}
