import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { ConnectionWizard } from "@/features/connections/ConnectionWizard";
import { describeProfileError } from "@/features/connections/errors";
import { useProfile } from "@/features/connections/hooks";

/** Route wrapper: admins only, loads the profile when editing. */
export function ConnectionWizardPage() {
  const { t } = useTranslation();
  const { query, canMutate } = useSession();
  const params = useParams();
  const id = params.id === undefined ? null : Number(params.id);
  const profile = useProfile(canMutate ? id : null);

  if (query.isPending) return <Loading />;
  if (!canMutate) return <Navigate to="/connections" replace />;
  if (id === null) return <ConnectionWizard />;
  if (profile.isPending) return <Loading />;
  if (profile.isError) {
    const described = describeProfileError(profile.error, "save");
    return (
      <div role="alert" className="flex flex-col gap-3 p-6">
        <p className="text-destructive">{t(described.messageKey, described.params)}</p>
      </div>
    );
  }
  return <ConnectionWizard key={profile.data.id} profile={profile.data} />;
}
