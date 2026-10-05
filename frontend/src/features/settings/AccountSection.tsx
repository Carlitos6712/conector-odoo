import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { describeAccountError } from "@/features/settings/errors";
import { Field, MIN_PASSWORD_LENGTH } from "@/features/settings/Field";
import { useChangePassword } from "@/features/settings/hooks";

/** Own password change: available to every role (the API allows it for operators too). */
export function AccountSection() {
  const { t } = useTranslation();
  const { toast } = useToast();
  const change = useChangePassword();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [localError, setLocalError] = useState<{ field: "next" | "confirm"; key: string } | null>(
    null,
  );

  const failure = change.error ? describeAccountError(change.error) : null;
  const fieldError = (field: "current" | "next" | "confirm") => {
    if (localError?.field === field) return t(localError.key);
    if (failure?.field === field) return t(failure.messageKey, failure.params);
    return null;
  };

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    change.reset();
    if (next.length < MIN_PASSWORD_LENGTH) {
      setLocalError({ field: "next", key: "settings.account.errors.tooShort" });
      return;
    }
    if (next !== confirm) {
      setLocalError({ field: "confirm", key: "settings.account.errors.mismatch" });
      return;
    }
    setLocalError(null);
    change.mutate(
      { current, next },
      {
        onSuccess: () => {
          setCurrent("");
          setNext("");
          setConfirm("");
          toast({ tone: "success", message: t("settings.account.done") });
        },
      },
    );
  }

  return (
    <Card role="region" aria-labelledby="settings-account">
      <CardHeader>
        <CardTitle id="settings-account">{t("settings.account.title")}</CardTitle>
        <CardDescription>{t("settings.account.description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} noValidate className="flex max-w-sm flex-col gap-4">
          <Field label={t("settings.account.current")} error={fieldError("current")}>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="current-password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
              />
            )}
          </Field>
          <Field
            label={t("settings.account.next")}
            hint={t("settings.account.policy")}
            error={fieldError("next")}
          >
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
              />
            )}
          </Field>
          <Field label={t("settings.account.confirm")} error={fieldError("confirm")}>
            {(props) => (
              <Input
                {...props}
                type="password"
                autoComplete="new-password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
              />
            )}
          </Field>
          {failure && !failure.field && (
            <p role="alert" className="text-sm text-destructive">
              {t(failure.messageKey, failure.params)}
            </p>
          )}
          <div>
            <Button type="submit" disabled={change.isPending || !current || !next || !confirm}>
              {change.isPending ? t("settings.account.submitting") : t("settings.account.submit")}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
