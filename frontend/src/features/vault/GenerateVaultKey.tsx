import { useTranslation } from "react-i18next";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { useGenerateVaultKey } from "@/features/vault/hooks";

/** "Generate key" action plus the backup warning. Used wherever the vault is found unconfigured. */
export function GenerateVaultKey({ onGenerated }: { onGenerated?: () => void }) {
  const { t } = useTranslation();
  const generate = useGenerateVaultKey();
  const conflict = generate.error instanceof ApiError && generate.error.status === 409;
  return (
    <div className="flex flex-col gap-2">
      <p className="text-sm text-muted-foreground">{t("vault.backupNote")}</p>
      <div>
        <Button
          type="button"
          variant="outline"
          disabled={generate.isPending}
          onClick={() => generate.mutate(undefined, { onSuccess: () => onGenerated?.() })}
        >
          {generate.isPending ? t("vault.generating") : t("vault.generate")}
        </Button>
      </div>
      {generate.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t(conflict ? "vault.alreadyConfigured" : "vault.generateFailed")}
        </p>
      )}
    </div>
  );
}
