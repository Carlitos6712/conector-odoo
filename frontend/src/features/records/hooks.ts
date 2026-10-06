import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteRecord,
  listRecords,
  RECORDS_KEY,
  recordsKey,
  updateRecord,
  type ListParams,
} from "@/features/records/api";
import type { RecordTarget } from "@/features/records/types";

export const useRecords = (params: ListParams | null) =>
  useQuery({
    queryKey: params ? recordsKey(params) : [...RECORDS_KEY, "idle"],
    queryFn: ({ signal }) => listRecords(params as ListParams, signal),
    enabled: params !== null,
    placeholderData: keepPreviousData,
    retry: false,
    refetchOnWindowFocus: false,
  });

export function useUpdateRecord(target: RecordTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, fields }: { id: string | number; fields: Record<string, unknown> }) =>
      updateRecord(target, id, fields),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY }),
  });
}

export function useDeleteRecord(target: RecordTarget) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string | number) => deleteRecord(target, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: RECORDS_KEY }),
  });
}
