import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type ReactNode } from 'react';

export interface Region {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ScanViewerHandle {
  fit: () => void;
  focusRegion: (r: Region) => void;
}

interface Props {
  src: string;
  alt: string;
  /** Natural size of the content (template px); the SVG overlay uses the same coordinate space. */
  width: number;
  height: number;
  overlay?: ReactNode;
  showOverlay?: boolean;
  /** Rendered over the viewport when the image fails to load. */
  errorContent?: ReactNode;
  toolbarExtra?: ReactNode;
}

interface View {
  s: number;
  tx: number;
  ty: number;
}

const MAX_SCALE = 6;
const clamp = (v: number, lo: number, hi: number) => Math.min(hi, Math.max(lo, v));

/** Zoomable / pannable image with an SVG overlay in the image's own coordinate space. */
export const ScanViewer = forwardRef<ScanViewerHandle, Props>(function ScanViewer(
  { src, alt, width, height, overlay, showOverlay = true, errorContent, toolbarExtra },
  ref,
) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const [view, setView] = useState<View>({ s: 0.3, tx: 0, ty: 0 });
  const viewRef = useRef(view);
  viewRef.current = view;
  const userMoved = useRef(false);
  const drag = useRef<{ id: number; x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const [imgState, setImgState] = useState<'loading' | 'ok' | 'error'>('loading');

  const fitScale = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return 0.3;
    const { width: cw, height: ch } = el.getBoundingClientRect();
    return Math.max(0.05, Math.min(cw / width, ch / height) * 0.98);
  }, [width, height]);

  const fit = useCallback(() => {
    const el = viewportRef.current;
    if (!el) return;
    const { width: cw, height: ch } = el.getBoundingClientRect();
    const s = fitScale();
    userMoved.current = false;
    setView({ s, tx: (cw - width * s) / 2, ty: (ch - height * s) / 2 });
  }, [fitScale, width, height]);

  const zoomAt = useCallback(
    (px: number, py: number, factor: number) => {
      const v = viewRef.current;
      const s = clamp(v.s * factor, fitScale() * 0.5, MAX_SCALE);
      const k = s / v.s;
      userMoved.current = true;
      setView({ s, tx: px - (px - v.tx) * k, ty: py - (py - v.ty) * k });
    },
    [fitScale],
  );

  const zoomCenter = (factor: number) => {
    const el = viewportRef.current;
    if (!el) return;
    const { width: cw, height: ch } = el.getBoundingClientRect();
    zoomAt(cw / 2, ch / 2, factor);
  };

  const actualSize = () => {
    const el = viewportRef.current;
    if (!el) return;
    const { width: cw, height: ch } = el.getBoundingClientRect();
    const v = viewRef.current;
    // keep the current centre point
    const cx = (cw / 2 - v.tx) / v.s;
    const cy = (ch / 2 - v.ty) / v.s;
    userMoved.current = true;
    setView({ s: 1, tx: cw / 2 - cx, ty: ch / 2 - cy });
  };

  useImperativeHandle(
    ref,
    () => ({
      fit,
      focusRegion: (r: Region) => {
        const el = viewportRef.current;
        if (!el) return;
        const { width: cw, height: ch } = el.getBoundingClientRect();
        const target = clamp(Math.min(cw / (r.w * 3), ch / (r.h * 6)), fitScale(), 2.5);
        const s = Math.max(viewRef.current.s, target);
        userMoved.current = true;
        setView({ s, tx: cw / 2 - (r.x + r.w / 2) * s, ty: ch / 2 - (r.y + r.h / 2) * s });
      },
    }),
    [fit, fitScale],
  );

  // Fit on mount / size change, and re-fit on container resize until the user zooms or pans.
  useLayoutEffect(() => {
    fit();
  }, [fit]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el || typeof ResizeObserver === 'undefined') return;
    const ro = new ResizeObserver(() => {
      if (!userMoved.current) fit();
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fit]);

  // Wheel zoom needs a non-passive native listener so the page does not scroll.
  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = el.getBoundingClientRect();
      const delta = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;
      zoomAt(e.clientX - rect.left, e.clientY - rect.top, Math.exp(-delta * 0.0015));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomAt]);

  useEffect(() => {
    setImgState('loading');
  }, [src]);

  const onPointerDown = (e: PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, tx: viewRef.current.tx, ty: viewRef.current.ty, moved: false };
    suppressClick.current = false;
  };
  const onPointerMove = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x;
    const dy = e.clientY - d.y;
    if (!d.moved && Math.hypot(dx, dy) > 4) {
      d.moved = true;
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    if (d.moved) {
      userMoved.current = true;
      setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }));
    }
  };
  const endDrag = (e: PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    if (d.moved) suppressClick.current = true;
    if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId);
    drag.current = null;
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = 60;
    let handled = true;
    if (e.key === '+' || e.key === '=') zoomCenter(1.25);
    else if (e.key === '-' || e.key === '_') zoomCenter(0.8);
    else if (e.key === 'f' || e.key === 'F') fit();
    else if (e.shiftKey && e.key === 'ArrowLeft') setView((v) => ({ ...v, tx: v.tx + step }));
    else if (e.shiftKey && e.key === 'ArrowRight') setView((v) => ({ ...v, tx: v.tx - step }));
    else if (e.shiftKey && e.key === 'ArrowUp') setView((v) => ({ ...v, ty: v.ty + step }));
    else if (e.shiftKey && e.key === 'ArrowDown') setView((v) => ({ ...v, ty: v.ty - step }));
    else handled = false;
    if (handled) {
      e.preventDefault();
      e.stopPropagation();
      userMoved.current = e.key !== 'f' && e.key !== 'F';
    }
  };

  return (
    <div className="viewer">
      <div className="viewer__toolbar" role="toolbar" aria-label="Image zoom">
        <button type="button" className="btn btn--sm" onClick={() => zoomCenter(1.25)} aria-label="Zoom in">
          +
        </button>
        <button type="button" className="btn btn--sm" onClick={() => zoomCenter(0.8)} aria-label="Zoom out">
          −
        </button>
        <button type="button" className="btn btn--sm" onClick={fit}>
          Fit
        </button>
        <button type="button" className="btn btn--sm" onClick={actualSize}>
          100%
        </button>
        <span className="viewer__zoom" aria-live="polite">
          {Math.round(view.s * 100)}%
        </span>
        {toolbarExtra}
      </div>
      <div
        ref={viewportRef}
        className="viewer__viewport"
        tabIndex={0}
        role="group"
        aria-label={`${alt}. Scroll to zoom, drag to pan, Shift+arrows to pan, plus/minus to zoom, F to fit.`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onClickCapture={(e) => {
          if (suppressClick.current) {
            e.stopPropagation();
            e.preventDefault();
            suppressClick.current = false;
          }
        }}
        onKeyDown={onKeyDown}
      >
        <div
          className="viewer__content"
          style={{ width, height, transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.s})` }}
        >
          <img
            src={src}
            alt={alt}
            width={width}
            height={height}
            draggable={false}
            onLoad={() => setImgState('ok')}
            onError={() => setImgState('error')}
            className="viewer__img"
          />
          {showOverlay && overlay && (
            <svg className="viewer__overlay" viewBox={`0 0 ${width} ${height}`} width={width} height={height} aria-hidden="false">
              {overlay}
            </svg>
          )}
        </div>
        {imgState === 'loading' && (
          <div className="viewer__msg" role="status">
            <span className="spinner" aria-hidden="true" /> Loading image…
          </div>
        )}
        {imgState === 'error' && <div className="viewer__msg viewer__msg--error">{errorContent ?? 'Image could not be loaded.'}</div>}
      </div>
    </div>
  );
});
