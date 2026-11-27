import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type TemplateGeometry } from '../api';

export interface AsyncState<T> {
  data: T | undefined;
  error: unknown;
  loading: boolean;
  reload: () => void;
  setData: (v: T | ((prev: T | undefined) => T)) => void;
}

/** Run an async loader when `deps` change; ignores stale responses. */
export function useAsync<T>(loader: () => Promise<T>, deps: unknown[]): AsyncState<T> {
  const [data, setDataState] = useState<T | undefined>(undefined);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    loaderRef
      .current()
      .then((v) => {
        if (alive) setDataState(v);
      })
      .catch((e) => {
        if (alive) setError(e);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
    // `loader` is read through a ref; callers list what it depends on in `deps`.
  }, [...deps, tick]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const setData = useCallback((v: T | ((prev: T | undefined) => T)) => {
    setDataState((prev) => (typeof v === 'function' ? (v as (p: T | undefined) => T)(prev) : v));
  }, []);
  return { data, error, loading, reload, setData };
}

const templateCache = new Map<string, Promise<TemplateGeometry>>();

/** Template geometry rarely changes, so it is fetched once per session. */
export function getTemplateCached(id: string): Promise<TemplateGeometry> {
  let p = templateCache.get(id);
  if (!p) {
    p = api.getTemplate(id).catch((e) => {
      templateCache.delete(id);
      throw e;
    });
    templateCache.set(id, p);
  }
  return p;
}

/** document.title helper. */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · OMR Scanner` : 'OMR Scanner';
  }, [title]);
}
