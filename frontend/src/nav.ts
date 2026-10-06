import {
  Cable,
  CalendarClock,
  Database,
  GitCompareArrows,
  History,
  ListChecks,
  LayoutDashboard,
  Settings,
  type LucideIcon,
} from "lucide-react";

export interface NavItem {
  /** Translation key suffix under `nav.` and route segment. */
  key:
    | "dashboard"
    | "connections"
    | "resources"
    | "records"
    | "mappings"
    | "jobs"
    | "runs"
    | "settings";
  path: string;
  icon: LucideIcon;
  /** Hidden from operators (the backend answers 403 to them anyway). */
  adminOnly?: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { key: "dashboard", path: "/", icon: LayoutDashboard },
  { key: "connections", path: "/connections", icon: Cable },
  { key: "resources", path: "/resources", icon: Database },
  { key: "records", path: "/records", icon: ListChecks },
  { key: "mappings", path: "/mappings", icon: GitCompareArrows },
  { key: "jobs", path: "/jobs", icon: CalendarClock },
  { key: "runs", path: "/runs", icon: History },
  { key: "settings", path: "/settings", icon: Settings },
];
