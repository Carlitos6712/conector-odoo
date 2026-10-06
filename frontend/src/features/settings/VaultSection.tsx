import { useTranslation } from "react-i18next";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { GenerateVaultKey } from "@/features/vault/GenerateVaultKey";
import { useVaultStatus } from "@/features/vault/hooks";

/** Admin-only: whether the credential vault has a key, and a way to create one when it has not. */
export function VaultSection() {
  const { t } = useTranslation();
  const status = useVaultStatus();
  if (!status.data) return null; // loading or unavailable: the section simply is not shown
  const { configured, source } = status.data;
  return (
    <Card role="region" aria-labelledby="settings-vault">
      <CardHeader>
        <CardTitle id="settings-vault">{t("vault.title")}</CardTitle>
        <CardDescription>
          {t(configured ? `vault.source.${source ?? "file"}` : "vault.notConfigured")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {!configured && <GenerateVaultKey />}
        {configured && source === "file" && (
          <p className="text-sm text-muted-foreground">{t("vault.backupNote")}</p>
        )}
      </CardContent>
    </Card>
  );
}
