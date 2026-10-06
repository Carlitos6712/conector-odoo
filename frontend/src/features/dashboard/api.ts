import { api } from "@/api/client";
import type { Dashboard } from "@/features/dashboard/types";

export const DASHBOARD_KEY = ["dashboard"] as const;

export const getDashboard = () => api.get<Dashboard>("/dashboard");
