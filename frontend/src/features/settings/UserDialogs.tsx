import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import type { AdminUser, Role } from "@/auth/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { describeUserError, type UserAction } from "@/features/settings/errors";
import { Field, MIN_PASSWORD_LENGTH } from "@/features/settings/Field";
import { useCreateUser, useDeleteUser, useUpdateUser } from "@/features/settings/hooks";

const ROLES: readonly Role[] = ["operator", "admin"];

function RoleSelect({
  id,
  value,
  onChange,
  props,
}: {
  id: string;
  value: Role;
  onChange: (role: Role) => void;
  props: Record<string, unknown>;
}) {
  const { t } = useTranslation();
  return (
    <Select {...props} id={id} value={value} onChange={(e) => onChange(e.target.value as Role)}>
      {ROLES.map((role) => (
        <option key={role} value={role}>
          {t(`session.roles.${role}`)}
        </option>
      ))}
    </Select>
  );
}

function useFailure(error: unknown, action: UserAction) {
  const { t } = useTranslation();
  const failure = error ? describeUserError(error, action) : null;
  return {
    field: (name: "username" | "password") =>
      failure?.field === name ? t(failure.messageKey, failure.params) : null,
    general: failure && !failure.field ? t(failure.messageKey, failure.params) : null,
  };
}

function GeneralError({ message }: { message: string | null }) {
  return message ? (
    <p role="alert" className="text-sm text-destructive">
      {message}
    </p>
  ) : null;
}

function CreateUserForm({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const create = useCreateUser();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("operator");
  const [local, setLocal] = useState<{ field: "username" | "password"; key: string } | null>(null);
  const failure = useFailure(create.error, "create");
  const error = (field: "username" | "password") =>
    local?.field === field ? t(local.key) : failure.field(field);

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    create.reset();
    if (!username.trim()) {
      setLocal({ field: "username", key: "settings.users.errors.usernameRequired" });
      return;
    }
    if (password.length < MIN_PASSWORD_LENGTH) {
      setLocal({ field: "password", key: "settings.users.errors.passwordTooShort" });
      return;
    }
    setLocal(null);
    create.mutate(
      { username: username.trim(), password, role },
      {
        onSuccess: () => {
          toast({ tone: "success", message: t("settings.users.create.done") });
          onClose();
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <DialogTitle>{t("settings.users.create.title")}</DialogTitle>
      <Field label={t("settings.users.fields.username")} error={error("username")}>
        {(props) => (
          <Input
            {...props}
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        )}
      </Field>
      <Field
        label={t("settings.users.fields.password")}
        hint={t("settings.users.passwordHint")}
        error={error("password")}
      >
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <Field label={t("settings.users.fields.role")}>
        {({ id, ...props }) => <RoleSelect id={id} value={role} onChange={setRole} props={props} />}
      </Field>
      <GeneralError message={failure.general} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={create.isPending}>
          {t("settings.users.create.submit")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function CreateUserDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent aria-describedby={undefined}>
        {open && <CreateUserForm onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function ChangeRoleForm({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const update = useUpdateUser();
  const [role, setRole] = useState<Role>(user.role);
  const failure = useFailure(update.error, "update");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    update.mutate(
      { id: user.id, patch: { role } },
      {
        onSuccess: () => {
          toast({ tone: "success", message: t("settings.users.role.done") });
          onClose();
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-4">
      <DialogTitle>{t("settings.users.role.title")}</DialogTitle>
      <DialogDescription>
        {t("settings.users.role.body", { name: user.username })}
      </DialogDescription>
      <Field label={t("settings.users.fields.role")}>
        {({ id, ...props }) => <RoleSelect id={id} value={role} onChange={setRole} props={props} />}
      </Field>
      <GeneralError message={failure.general} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={update.isPending || role === user.role}>
          {t("settings.users.role.submit")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ChangeRoleDialog({
  user,
  onClose,
}: {
  user: AdminUser | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={user !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>{user && <ChangeRoleForm user={user} onClose={onClose} />}</DialogContent>
    </Dialog>
  );
}

function ResetPasswordForm({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const update = useUpdateUser();
  const [password, setPassword] = useState("");
  const [tooShort, setTooShort] = useState(false);
  const failure = useFailure(update.error, "reset");

  function onSubmit(event: FormEvent) {
    event.preventDefault();
    update.reset();
    if (password.length < MIN_PASSWORD_LENGTH) {
      setTooShort(true);
      return;
    }
    setTooShort(false);
    update.mutate(
      { id: user.id, patch: { password } },
      {
        onSuccess: () => {
          toast({ tone: "success", message: t("settings.users.reset.done") });
          onClose();
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="flex flex-col gap-4">
      <DialogTitle>{t("settings.users.reset.title")}</DialogTitle>
      <DialogDescription>
        {t("settings.users.reset.body", { name: user.username })}
      </DialogDescription>
      <Field
        label={t("settings.users.fields.newPassword")}
        hint={t("settings.users.passwordHint")}
        error={tooShort ? t("settings.users.errors.passwordTooShort") : failure.field("password")}
      >
        {(props) => (
          <Input
            {...props}
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        )}
      </Field>
      <GeneralError message={failure.general} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={update.isPending}>
          {t("settings.users.reset.submit")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function ResetPasswordDialog({
  user,
  onClose,
}: {
  user: AdminUser | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={user !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>{user && <ResetPasswordForm user={user} onClose={onClose} />}</DialogContent>
    </Dialog>
  );
}

function DeleteUserBody({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const remove = useDeleteUser();
  const failure = useFailure(remove.error, "delete");
  return (
    <>
      <DialogTitle>{t("settings.users.delete.title")}</DialogTitle>
      <DialogDescription>
        {t("settings.users.delete.body", { name: user.username })}
      </DialogDescription>
      <GeneralError message={failure.general} />
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button
          variant="destructive"
          disabled={remove.isPending}
          onClick={() =>
            remove.mutate(user.id, {
              onSuccess: () => {
                toast({ tone: "success", message: t("settings.users.delete.done") });
                onClose();
              },
            })
          }
        >
          {t("common.delete")}
        </Button>
      </DialogFooter>
    </>
  );
}

/** Destructive confirmation; a 409 (last administrator) stays open and explains why. */
export function DeleteUserDialog({
  user,
  onClose,
}: {
  user: AdminUser | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={user !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent role="alertdialog">
        {user && <DeleteUserBody user={user} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}
