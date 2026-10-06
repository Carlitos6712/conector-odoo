import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { generateVaultKey, getVaultStatus, VAULT_KEY } from "@/features/vault/api";

export const useVaultStatus = (enabled = true) =>
  useQuery({ queryKey: VAULT_KEY, queryFn: getVaultStatus, enabled });

export function useGenerateVaultKey() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: generateVaultKey,
    // Also on failure: a 409 means a key appeared meanwhile, so the status is stale.
    onSettled: () => queryClient.invalidateQueries({ queryKey: VAULT_KEY }),
  });
}
