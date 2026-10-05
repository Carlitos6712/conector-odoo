import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

interface PaginationProps {
  /** 1-based current page. */
  page: number;
  /** Lists without a total only know whether a next page exists. */
  hasNext: boolean;
  onPageChange: (page: number) => void;
}

export function Pagination({ page, hasNext, onPageChange }: PaginationProps) {
  const { t } = useTranslation();
  return (
    <nav aria-label={t("common.pagination.label")} className="flex items-center justify-end gap-3">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        <ChevronLeft aria-hidden className="size-4" />
        {t("common.pagination.previous")}
      </Button>
      <span aria-current="page" className="text-sm text-muted-foreground">
        {t("common.pagination.page", { page })}
      </span>
      <Button
        variant="outline"
        size="sm"
        disabled={!hasNext}
        onClick={() => onPageChange(page + 1)}
      >
        {t("common.pagination.next")}
        <ChevronRight aria-hidden className="size-4" />
      </Button>
    </nav>
  );
}
