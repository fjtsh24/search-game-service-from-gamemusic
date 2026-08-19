"use client";

import { useEffect } from "react";

export default function SentryInit() {
  useEffect(() => {
    if (process.env.NEXT_PUBLIC_SENTRY_DSN) {
      import("../../sentry.client.config");
    }
  }, []);
  return null;
}
