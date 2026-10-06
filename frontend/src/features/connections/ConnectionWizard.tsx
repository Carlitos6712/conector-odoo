import { Fragment, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Steps } from "@/components/ui/steps";
import { useToast } from "@/components/ui/toast";
import { describeActiveOdooError, describeProfileError } from "@/features/connections/errors";
import {
  AUTH_METHODS,
  emptyState,
  hasAllSecretsTyped,
  requiredSecrets,
  stateFromProfile,
  toInput,
  usesTokenUrl,
  usesUserPassword,
  validate,
  type FieldErrors,
  type FormState,
} from "@/features/connections/form";
import { FormField } from "@/features/connections/FormField";
import {
  useActivateOdoo,
  useCreateProfile,
  useTestDraft,
  useTestSaved,
  useUpdateProfile,
} from "@/features/connections/hooks";
import { TestResultView } from "@/features/connections/TestResultView";
import { ApiError } from "@/api/client";
import { GenerateVaultKey } from "@/features/vault/GenerateVaultKey";
import type { Profile, ProfileKind, SecretField } from "@/features/connections/types";

const STEP_IDS = ["kind", "data", "test", "review"] as const;
type StepId = (typeof STEP_IDS)[number];

const SECRET_LABEL: Record<SecretField, string> = {
  api_key: "apiKey",
  token: "bearer",
  client_id: "clientId",
  client_secret: "clientSecret",
  password: "password",
};

/** Optional in the OAuth2 form: either the client secret or the username + password is enough. */
const OPTIONAL_WITH_USER = new Set<SecretField>(["client_secret", "password"]);

const isVaultMissing = (error: unknown) =>
  error instanceof ApiError && error.code === "vault_not_configured";

/** Four-step create/edit wizard. Typed credentials live only in this component's state. */
export function ConnectionWizard({ profile }: { profile?: Profile }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const editing = profile !== undefined;
  const stored = profile?.has_secret ?? {};

  const [state, setState] = useState<FormState>(() =>
    profile ? stateFromProfile(profile) : emptyState(),
  );
  const [step, setStep] = useState(editing ? 1 : 0);
  const [errors, setErrors] = useState<FieldErrors>({});
  const [saveError, setSaveError] = useState<string | null>(null);
  const [vaultMissing, setVaultMissing] = useState(false);
  // Set once the profile exists server-side, so a failed activation never re-creates it.
  const [savedId, setSavedId] = useState<number | null>(null);
  const { toast } = useToast();

  const create = useCreateProfile();
  const update = useUpdateProfile();
  const activate = useActivateOdoo();
  const testDraft = useTestDraft();
  const testSaved = useTestSaved();
  const testing = testDraft.isPending || testSaved.isPending;
  const testResult = testDraft.data ?? testSaved.data ?? null;
  const testError = testDraft.error ?? testSaved.error ?? null;
  const showVaultPrompt = vaultMissing || isVaultMissing(testError);

  // Drop every mutation's variables (they carry credentials) when the wizard goes away.
  const resets = [create.reset, update.reset, activate.reset, testDraft.reset, testSaved.reset];
  useEffect(
    () => () => resets.forEach((reset) => reset()),
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `reset` functions are stable
    [],
  );

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setState((prev) => ({ ...prev, [key]: value }));
  const setSecret = (field: SecretField, value: string) =>
    setState((prev) => ({ ...prev, secrets: { ...prev.secrets, [field]: value } }));
  const message = (key: string | undefined) => (key ? t(key) : undefined);

  function goTo(next: number) {
    if (next < 2) {
      testDraft.reset();
      testSaved.reset();
    }
    setStep(next);
  }

  function next() {
    const id: StepId = STEP_IDS[step] ?? "kind";
    if (id === "kind" || id === "data") {
      const found = validate(id, state, stored);
      setErrors(found);
      if (Object.keys(found).length > 0) return;
    }
    setSaveError(null);
    goTo(step + 1);
  }

  function finish(name: string, activated: boolean) {
    if (activated) {
      toast({ tone: "success", message: t("connections.active.activate.done", { name }) });
    }
    void navigate("/connections");
  }

  function runActivation(id: number, name: string) {
    activate.mutate(id, { onSuccess: () => finish(name, true) });
  }

  function save(activateAfter: boolean) {
    const input = toInput(state);
    const onError = (error: unknown) => {
      const described = describeProfileError(error, "save");
      setSaveError(t(described.messageKey, described.params));
      if (isVaultMissing(error)) setVaultMissing(true);
      if (Object.keys(described.fieldErrors).length > 0) {
        setErrors(described.fieldErrors);
        goTo(1);
      }
    };
    const onSuccess = (saved: Profile) => {
      setSavedId(saved.id);
      if (activateAfter) runActivation(saved.id, saved.name);
      else finish(saved.name, false);
    };
    const existing = profile?.id ?? savedId;
    if (existing !== null) update.mutate({ id: existing, input }, { onSuccess, onError });
    else create.mutate(input, { onSuccess, onError });
  }

  function onKeyGenerated() {
    setVaultMissing(false);
    setSaveError(null);
    testDraft.reset();
    testSaved.reset();
  }

  const saving = create.isPending || update.isPending || activate.isPending;
  const activationFailure = activate.error ? describeActiveOdooError(activate.error) : null;
  const canDraftTest = hasAllSecretsTyped(state);
  const kindLabel = (kind: ProfileKind) => t(`connections.kinds.${kind}`);
  const stepId = STEP_IDS[step] ?? "kind";

  const secretField = (field: SecretField, label: string) => (
    <FormField
      name={field}
      label={label}
      error={message(errors[field])}
      hint={editing && stored[field] ? t("connections.wizard.secretStored") : undefined}
      required={!stored[field] && !(usesUserPassword(state) && OPTIONAL_WITH_USER.has(field))}
    >
      {(props) => (
        <Input
          {...props}
          type="password"
          autoComplete="new-password"
          value={state.secrets[field]}
          onChange={(e) => setSecret(field, e.target.value)}
        />
      )}
    </FormField>
  );

  return (
    <section className="flex max-w-2xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">
        {t(editing ? "connections.wizard.titleEdit" : "connections.wizard.titleCreate")}
      </h1>
      <Steps
        label={t("connections.wizard.stepsLabel")}
        current={step}
        items={STEP_IDS.map((id) => ({ id, label: t(`connections.wizard.steps.${id}`) }))}
      />
      <h2 className="text-lg font-semibold">{t(`connections.wizard.headings.${stepId}`)}</h2>

      {saveError && (
        <p role="alert" className="text-sm text-destructive">
          {saveError}
        </p>
      )}

      {showVaultPrompt && <GenerateVaultKey onGenerated={onKeyGenerated} />}

      {stepId === "kind" && (
        <fieldset className="flex flex-col gap-3">
          <legend className="sr-only">{t("connections.wizard.headings.kind")}</legend>
          {(["odoo", "rest"] as const).map((kind) => (
            <div key={kind} className="flex items-start gap-3 rounded-md border p-3">
              <input
                type="radio"
                id={`kind-${kind}`}
                name="kind"
                className="mt-1"
                checked={state.type === kind}
                disabled={editing}
                aria-describedby={`kind-${kind}-desc`}
                onChange={() => set("type", kind)}
              />
              <div className="flex flex-col">
                <label htmlFor={`kind-${kind}`} className="font-medium">
                  {kindLabel(kind)}
                </label>
                <span id={`kind-${kind}-desc`} className="text-sm text-muted-foreground">
                  {t(`connections.wizard.kindDescriptions.${kind}`)}
                </span>
              </div>
            </div>
          ))}
          {errors.type && <p className="text-sm text-destructive">{t(errors.type)}</p>}
        </fieldset>
      )}

      {stepId === "data" && (
        <div className="flex flex-col gap-4">
          <FormField
            name="name"
            label={t("connections.wizard.fields.name")}
            error={message(errors.name)}
          >
            {(props) => (
              <Input {...props} value={state.name} onChange={(e) => set("name", e.target.value)} />
            )}
          </FormField>
          <FormField
            name="base_url"
            label={t("connections.wizard.fields.baseUrl")}
            error={message(errors.base_url)}
          >
            {(props) => (
              <Input
                {...props}
                type="url"
                inputMode="url"
                placeholder="https://"
                value={state.base_url}
                onChange={(e) => set("base_url", e.target.value)}
              />
            )}
          </FormField>

          {state.type === "odoo" ? (
            <>
              <FormField
                name="odoo_db"
                label={t("connections.wizard.fields.odooDb")}
                error={message(errors.odoo_db)}
              >
                {(props) => (
                  <Input
                    {...props}
                    value={state.odoo_db}
                    onChange={(e) => set("odoo_db", e.target.value)}
                  />
                )}
              </FormField>
              <FormField
                name="odoo_login"
                label={t("connections.wizard.fields.odooLogin")}
                error={message(errors.odoo_login)}
              >
                {(props) => (
                  <Input
                    {...props}
                    value={state.odoo_login}
                    onChange={(e) => set("odoo_login", e.target.value)}
                  />
                )}
              </FormField>
              {secretField("api_key", t("connections.wizard.fields.apiKey"))}
            </>
          ) : (
            <>
              <FormField
                name="auth_method"
                label={t("connections.wizard.fields.authType")}
                error={message(errors.auth_method)}
              >
                {(props) => (
                  <Select
                    {...props}
                    value={state.auth_method}
                    onChange={(e) => set("auth_method", e.target.value as FormState["auth_method"])}
                  >
                    {AUTH_METHODS.map((method) => (
                      <option key={method} value={method}>
                        {t(`connections.wizard.auth.${method}`)}
                      </option>
                    ))}
                  </Select>
                )}
              </FormField>
              {state.auth_method === "api_key" && (
                <FormField
                  name="api_key_header"
                  label={t("connections.wizard.fields.apiKeyHeader")}
                  error={message(errors.api_key_header)}
                >
                  {(props) => (
                    <Input
                      {...props}
                      value={state.api_key_header}
                      onChange={(e) => set("api_key_header", e.target.value)}
                    />
                  )}
                </FormField>
              )}
              {usesTokenUrl(state) && (
                <>
                  <FormField
                    name="token_url"
                    label={t("connections.wizard.fields.tokenUrl")}
                    error={message(errors.token_url)}
                    hint={
                      state.auth_method === "oidc"
                        ? t("connections.wizard.tokenUrlOidcHint")
                        : undefined
                    }
                    required={state.auth_method === "oauth2_client_credentials"}
                  >
                    {(props) => (
                      <Input
                        {...props}
                        type="url"
                        inputMode="url"
                        value={state.token_url}
                        onChange={(e) => set("token_url", e.target.value)}
                      />
                    )}
                  </FormField>
                  <FormField
                    name="scope"
                    label={t("connections.wizard.fields.scope")}
                    required={false}
                  >
                    {(props) => (
                      <Input
                        {...props}
                        value={state.scope}
                        onChange={(e) => set("scope", e.target.value)}
                      />
                    )}
                  </FormField>
                </>
              )}
              {requiredSecrets(state).map((field) => (
                <Fragment key={field}>
                  {field === "password" && (
                    <FormField
                      name="username"
                      label={t("connections.wizard.fields.username")}
                      hint={t("connections.wizard.userPasswordHint")}
                      required={false}
                    >
                      {(props) => (
                        <Input
                          {...props}
                          autoComplete="off"
                          value={state.username}
                          onChange={(e) => set("username", e.target.value)}
                        />
                      )}
                    </FormField>
                  )}
                  {secretField(field, t(`connections.wizard.fields.${SECRET_LABEL[field]}`))}
                </Fragment>
              ))}
            </>
          )}

          <details className="rounded-md border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              {t("connections.wizard.advanced")}
            </summary>
            <div className="mt-3 flex flex-col gap-4">
              <FormField
                name="timeout_seconds"
                label={t("connections.wizard.fields.timeout")}
                error={message(errors.timeout_seconds)}
              >
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={1}
                    value={state.timeout_seconds}
                    onChange={(e) => set("timeout_seconds", e.target.value)}
                  />
                )}
              </FormField>
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={state.tls_verify}
                  onChange={(e) => set("tls_verify", e.target.checked)}
                />
                {t("connections.wizard.fields.tlsVerify")}
              </label>
            </div>
          </details>
        </div>
      )}

      {stepId === "test" && (
        <div className="flex flex-col gap-4">
          <p className="text-sm text-muted-foreground">{t("connections.test.intro")}</p>
          <div className="flex flex-wrap gap-2">
            <Button
              variant="secondary"
              disabled={testing || !canDraftTest}
              onClick={() => testDraft.mutate(toInput(state))}
            >
              {t("connections.test.run")}
            </Button>
            {editing && profile && !canDraftTest && (
              <Button
                variant="outline"
                disabled={testing}
                onClick={() => testSaved.mutate(profile.id)}
              >
                {t("connections.test.runSaved")}
              </Button>
            )}
          </div>
          {!canDraftTest && (
            <p className="text-sm text-muted-foreground">{t("connections.test.needsSecrets")}</p>
          )}
          {testing && (
            <p role="status" className="text-sm text-muted-foreground">
              {t("connections.test.running")}
            </p>
          )}
          {testError && (
            <p role="alert" className="text-sm text-destructive">
              {(() => {
                const described = describeProfileError(testError, "test");
                return t(described.messageKey, described.params);
              })()}
            </p>
          )}
          {testResult && <TestResultView result={testResult} />}
          <p className="text-sm text-muted-foreground">{t("connections.test.optional")}</p>
        </div>
      )}

      {stepId === "review" && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-muted-foreground">{t("connections.wizard.fields.name")}</dt>
          <dd>{state.name}</dd>
          <dt className="text-muted-foreground">{t("connections.columns.kind")}</dt>
          <dd>{state.type ? kindLabel(state.type) : ""}</dd>
          <dt className="text-muted-foreground">{t("connections.wizard.fields.baseUrl")}</dt>
          <dd className="break-all">{state.base_url}</dd>
          {state.type === "odoo" ? (
            <>
              <dt className="text-muted-foreground">{t("connections.wizard.fields.odooDb")}</dt>
              <dd>{state.odoo_db}</dd>
              <dt className="text-muted-foreground">{t("connections.wizard.fields.odooLogin")}</dt>
              <dd>{state.odoo_login}</dd>
            </>
          ) : (
            <>
              <dt className="text-muted-foreground">{t("connections.wizard.fields.authType")}</dt>
              <dd>{t(`connections.wizard.auth.${state.auth_method}`)}</dd>
            </>
          )}
          <dt className="text-muted-foreground">{t("connections.wizard.review.credentials")}</dt>
          <dd>
            {Object.values(state.secrets).some((v) => v !== "")
              ? t("connections.wizard.review.credentialsNew")
              : t("connections.wizard.review.credentialsKept")}
          </dd>
          <dt className="text-muted-foreground">{t("connections.columns.status")}</dt>
          <dd>
            {testResult === null
              ? t("connections.status.untested")
              : testResult.ok
                ? t("connections.status.ok")
                : t("connections.test.failedAt", {
                    step: t(`connections.steps.${testResult.failed_step ?? ""}`, {
                      defaultValue: testResult.failed_step ?? "",
                    }),
                  })}
          </dd>
        </dl>
      )}

      {stepId === "review" && activationFailure && (
        <div className="flex flex-col gap-3">
          <p role="alert" className="text-sm text-destructive">
            {t("connections.wizard.activation.savedNotActive")}
          </p>
          <p className="text-sm text-destructive">
            {t(activationFailure.messageKey, activationFailure.params)}
          </p>
          {activationFailure.result && <TestResultView result={activationFailure.result} />}
        </div>
      )}

      <div className="flex justify-between gap-2">
        <Button
          variant="outline"
          onClick={() => (step === 0 ? void navigate("/connections") : goTo(step - 1))}
        >
          {step === 0 ? t("common.cancel") : t("connections.wizard.back")}
        </Button>
        {stepId === "review" ? (
          savedId !== null && activationFailure ? (
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => finish("", false)}>
                {t("connections.wizard.activation.goToList")}
              </Button>
              <Button disabled={saving} onClick={() => runActivation(savedId, state.name)}>
                {t("connections.wizard.activation.retry")}
              </Button>
            </div>
          ) : (
            <div className="flex gap-2">
              <Button variant="outline" disabled={saving} onClick={() => save(false)}>
                {saving && !activate.isPending
                  ? t("connections.wizard.saving")
                  : t("connections.wizard.save")}
              </Button>
              {state.type === "odoo" && (
                <Button disabled={saving} onClick={() => save(true)}>
                  {activate.isPending
                    ? t("connections.wizard.activation.running")
                    : t("connections.wizard.saveAndActivate")}
                </Button>
              )}
            </div>
          )
        ) : (
          <Button onClick={next}>{t("connections.wizard.next")}</Button>
        )}
      </div>
    </section>
  );
}
