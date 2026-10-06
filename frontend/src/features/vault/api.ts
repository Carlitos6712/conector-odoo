import { api } from "@/api/client";

export const VAULT_KEY = ["vault", "status"] as const;

export interface VaultStatus {
  configured: boolean;
  source: "env" | "file" | null;
}

export const getVaultStatus = () => api.get<VaultStatus>("/vault/status");

/** Creates the key server-side; the key itself never reaches the browser. */
export const generateVaultKey = () => api.post<VaultStatus>("/vault/generate");
