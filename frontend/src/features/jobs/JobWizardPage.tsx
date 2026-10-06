import { useTranslation } from "react-i18next";
import { Navigate, useParams } from "react-router-dom";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { describeJobError } from "@/features/jobs/errors";
import { useJob } from "@/features/jobs/hooks";
import { JobWizard } from "@/features/jobs/JobWizard";

/** Route wrapper: admins only, loads the job when editing. */
export function JobWizardPage() {
  const { t } = useTranslation();
  const { query, canMutate } = useSession();
  const params = useParams();
  const id = params.id === undefined ? null : Number(params.id);
  const job = useJob(canMutate ? id : null);

  if (query.isPending) return <Loading />;
  if (!canMutate) return <Navigate to="/jobs" replace />;
  if (id === null) return <JobWizard />;
  if (job.isPending) return <Loading />;
  if (job.isError) {
    const described = describeJobError(job.error, "load");
    return (
      <div role="alert" className="flex flex-col gap-3 p-6">
        <p className="text-destructive">{t(described.messageKey, described.params)}</p>
      </div>
    );
  }
  return <JobWizard key={job.data.id} job={job.data} />;
}
