import { Component, type ErrorInfo, type ReactNode } from "react";
import { withTranslation, type WithTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

class Boundary extends Component<WithTranslation & { children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Unhandled UI error", error, info.componentStack);
  }

  render() {
    const { t, children } = this.props;
    if (!this.state.failed) return children;
    return (
      <div
        role="alert"
        className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-center"
      >
        <h1 className="text-xl font-semibold">{t("errors.boundaryTitle")}</h1>
        <p className="text-muted-foreground">{t("errors.boundaryBody")}</p>
        <Button onClick={() => window.location.reload()}>{t("errors.reload")}</Button>
      </div>
    );
  }
}

export const ErrorBoundary = withTranslation()(Boundary);
