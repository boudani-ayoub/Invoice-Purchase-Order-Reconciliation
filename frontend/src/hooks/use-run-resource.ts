"use client";

import { useEffect, useState } from "react";

export function useRunResource<T>(
  key: string,
  load: (signal: AbortSignal) => Promise<T>,
) {
  const [revision, setRevision] = useState(0);
  const identity = `${key}:${revision}`;
  const [state, setState] = useState<{ key: string; value?: T; error?: Error }>(
    { key: "" },
  );
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal).then(
      (value) => {
        if (!controller.signal.aborted) setState({ key: identity, value });
      },
      (error: unknown) => {
        if (!controller.signal.aborted)
          setState({
            key: identity,
            error:
              error instanceof Error
                ? error
                : new Error("Unable to load saved history."),
          });
      },
    );
    return () => controller.abort();
  }, [identity, load]);
  return {
    value: state.key === identity ? state.value : undefined,
    error: state.key === identity ? state.error : undefined,
    loading: state.key !== identity,
    reload: () => setRevision((current) => current + 1),
  };
}
