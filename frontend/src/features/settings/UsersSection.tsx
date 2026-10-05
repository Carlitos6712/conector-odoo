import { KeyRound, Plus, Trash2, UserCog } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import type { AdminUser } from "@/auth/api";
import { useSession } from "@/auth/useSession";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { formatDateTime } from "@/features/mappings/format";
import { useUsers } from "@/features/settings/hooks";
import {
  ChangeRoleDialog,
  CreateUserDialog,
  DeleteUserDialog,
  ResetPasswordDialog,
} from "@/features/settings/UserDialogs";

/**
 * Admin-only user management. Your own row is protected on the client (no demotion, no deletion,
 * password changes go through "Mi cuenta" so the session is not killed by a reset); the backend
 * still enforces the last-administrator rule and its 409 is surfaced by the dialogs.
 */
export function UsersSection() {
  const { t } = useTranslation();
  const { user: me } = useSession();
  const users = useUsers();
  const [creating, setCreating] = useState(false);
  const [roleTarget, setRoleTarget] = useState<AdminUser | null>(null);
  const [resetTarget, setResetTarget] = useState<AdminUser | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<AdminUser | null>(null);

  return (
    <Card role="region" aria-labelledby="settings-users">
      <CardHeader className="flex-row flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1.5">
          <CardTitle id="settings-users">{t("settings.users.title")}</CardTitle>
          <CardDescription>{t("settings.users.description")}</CardDescription>
        </div>
        <Button onClick={() => setCreating(true)}>
          <Plus aria-hidden className="size-4" />
          {t("settings.users.new")}
        </Button>
      </CardHeader>
      <CardContent>
        {users.isPending ? (
          <Loading />
        ) : users.isError ? (
          <ErrorState error={users.error} onRetry={() => void users.refetch()} />
        ) : users.data.length === 0 ? (
          <EmptyState message={t("settings.users.empty")} />
        ) : (
          <Table aria-label={t("settings.users.title")}>
            <TableHeader>
              <TableRow>
                <TableHead>{t("settings.users.columns.username")}</TableHead>
                <TableHead>{t("settings.users.columns.role")}</TableHead>
                <TableHead>{t("settings.users.columns.created")}</TableHead>
                <TableHead>{t("settings.users.columns.actions")}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {users.data.map((row) => {
                const self = row.id === me?.id;
                const hint = self ? t("settings.users.actions.selfHint") : undefined;
                return (
                  <TableRow key={row.id}>
                    <TableCell className="font-medium">
                      <span>{row.username}</span>
                      {self && (
                        <Badge variant="outline" className="ml-2">
                          {t("settings.users.you")}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>{t(`session.roles.${row.role}`)}</TableCell>
                    <TableCell>{formatDateTime(row.created_at)}</TableCell>
                    <TableCell>
                      <div className="flex gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          title={hint}
                          aria-label={t("settings.users.actions.changeRole", {
                            name: row.username,
                          })}
                          disabled={self}
                          onClick={() => setRoleTarget(row)}
                        >
                          <UserCog aria-hidden className="size-4" />
                        </Button>
                        {!self && (
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("settings.users.actions.resetPassword", {
                              name: row.username,
                            })}
                            onClick={() => setResetTarget(row)}
                          >
                            <KeyRound aria-hidden className="size-4" />
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon"
                          title={hint}
                          aria-label={t("settings.users.actions.remove", { name: row.username })}
                          disabled={self}
                          onClick={() => setDeleteTarget(row)}
                        >
                          <Trash2 aria-hidden className="size-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </CardContent>
      <CreateUserDialog open={creating} onClose={() => setCreating(false)} />
      <ChangeRoleDialog user={roleTarget} onClose={() => setRoleTarget(null)} />
      <ResetPasswordDialog user={resetTarget} onClose={() => setResetTarget(null)} />
      <DeleteUserDialog user={deleteTarget} onClose={() => setDeleteTarget(null)} />
    </Card>
  );
}
