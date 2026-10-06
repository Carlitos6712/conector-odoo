import type { Translation } from "@/i18n/types";

/** English resources: must stay in key parity with Spanish (enforced by a test). */
export const en: Translation = {
  app: { name: "Connector", skipToContent: "Skip to content" },
  common: {
    loading: "Loading…",
    retry: "Retry",
    empty: "No data yet.",
    unexpectedError: "An unexpected error occurred.",
    networkError: "Cannot reach the server.",
    backHome: "Back to home",
  },
  login: {
    title: "Sign in",
    description: "Access the connector administration panel.",
    username: "Username",
    password: "Password",
    submit: "Sign in",
    submitting: "Signing in…",
    errors: {
      invalid_credentials: "Wrong username or password.",
      rate_limited: "Too many attempts. Try again in {{seconds}} seconds.",
      rate_limited_unknown: "Too many attempts. Try again later.",
    },
  },
  nav: {
    label: "Main navigation",
    dashboard: "Dashboard",
    connections: "Connections",
    resources: "Resources",
    mappings: "Mappings",
    jobs: "Jobs",
    runs: "Runs",
    settings: "Settings",
  },
  session: {
    logout: "Sign out",
    signedInAs: "Signed in as {{username}}",
    readOnly: "Read-only mode: your role cannot modify data.",
    roles: { admin: "Administrator", operator: "Operator" },
  },
  placeholder: { comingSoon: "This section will be available soon." },
  errors: {
    notFoundTitle: "Page not found",
    boundaryTitle: "Something went wrong",
    boundaryBody: "The screen could not be displayed. Reload the page to try again.",
    reload: "Reload",
  },
};
