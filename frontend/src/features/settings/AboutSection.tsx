import { useTranslation } from "react-i18next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useSession } from "@/auth/useSession";
import { formatDateTime } from "@/features/mappings/format";

/**
 * Read-only facts the API really exposes: the signed-in user and the session expiry
 * (`/auth/me`). `/health` carries no version and no endpoint reports the scheduler flag, so
 * neither is shown rather than invented.
 */
export function AboutSection() {
  const { t } = useTranslation();
  const { query, user } = useSession();
  const expiresAt = query.data?.expires_at;
  return (
    <Card role="region" aria-labelledby="settings-about">
      <CardHeader>
        <CardTitle id="settings-about">{t("settings.about.title")}</CardTitle>
        <CardDescription>{t("settings.about.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {user && (
          <dl className="grid max-w-sm grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{t("settings.about.user")}</dt>
            <dd>{user.username}</dd>
            <dt className="text-muted-foreground">{t("settings.about.role")}</dt>
            <dd>{t(`session.roles.${user.role}`)}</dd>
          </dl>
        )}
        {expiresAt && (
          <p className="mt-3 text-sm text-muted-foreground">
            {t("settings.about.session", { date: formatDateTime(expiresAt) })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
