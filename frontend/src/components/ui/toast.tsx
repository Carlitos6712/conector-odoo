import { X } from "lucide-react";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface ToastInput {
  tone: "success" | "error";
  message: string;
  /** An in-app link shown next to the message, e.g. "Ver ejecución". */
  action?: { label: string; to: string };
}

interface ToastItem extends ToastInput {
  id: number;
}

interface ToastApi {
  toast: (input: ToastInput) => void;
}

const DISMISS_AFTER_MS = 8000;
const NOOP: ToastApi = { toast: () => {} };
const ToastContext = createContext<ToastApi>(NOOP);

/** Without a provider (a page rendered on its own) toasts are silently dropped. */
export const useToast = () => useContext(ToastContext);

function ToastView({ item, onClose }: { item: ToastItem; onClose: (id: number) => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    const timer = setTimeout(() => onClose(item.id), DISMISS_AFTER_MS);
    return () => clearTimeout(timer);
  }, [item.id, onClose]);
  const error = item.tone === "error";
  return (
    <div
      role={error ? "alert" : "status"}
      className={cn(
        "pointer-events-auto flex items-start gap-3 rounded-lg border border-l-4 border-l-success bg-card p-3 text-sm shadow-lift",
        error &&
          "border-destructive/40 border-l-destructive bg-destructive-soft text-destructive-soft-foreground",
      )}
    >
      <p className="flex-1">{item.message}</p>
      {item.action && (
        <Link to={item.action.to} className="font-medium underline underline-offset-2">
          {item.action.label}
        </Link>
      )}
      <Button
        variant="ghost"
        size="icon"
        className="-m-2 size-7"
        aria-label={t("common.dismiss")}
        onClick={() => onClose(item.id)}
      >
        <X aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

/** Stacks short notifications bottom-right; each closes by itself after a few seconds. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const [items, setItems] = useState<ToastItem[]>([]);
  const nextId = useRef(1);

  const close = useCallback(
    (id: number) => setItems((prev) => prev.filter((item) => item.id !== id)),
    [],
  );
  const toast = useCallback((input: ToastInput) => {
    setItems((prev) => [...prev, { ...input, id: nextId.current++ }]);
  }, []);
  const api = useMemo(() => ({ toast }), [toast]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div
        role="region"
        aria-label={t("common.notifications")}
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 max-w-[calc(100vw-2rem)] flex-col gap-2"
      >
        {items.map((item) => (
          <ToastView key={item.id} item={item} onClose={close} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}
