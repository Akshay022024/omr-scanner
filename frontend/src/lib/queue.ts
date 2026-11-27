import type { Id, ScanRecord } from '../api/types';

export interface QueueNav<T> {
  prev?: T;
  next?: T;
  /** 1-based position of the current item inside the queue, 0 if it is not in the queue. */
  position: number;
  total: number;
}

/**
 * Prev/next items matching `inQueue`, relative to the current item's position in `items`.
 * Works even when the current item itself is not in the queue (e.g. already fixed).
 */
export function queueNeighbours<T extends { id: Id }>(items: T[], currentId: Id, inQueue: (t: T) => boolean): QueueNav<T> {
  const idx = items.findIndex((t) => String(t.id) === String(currentId));
  const queue = items.filter(inQueue);
  const nav: QueueNav<T> = { position: 0, total: queue.length };
  if (idx < 0) {
    nav.next = queue[0];
    return nav;
  }
  for (let i = idx - 1; i >= 0; i--) {
    if (inQueue(items[i])) {
      nav.prev = items[i];
      break;
    }
  }
  for (let i = idx + 1; i < items.length; i++) {
    if (inQueue(items[i])) {
      nav.next = items[i];
      break;
    }
  }
  const qi = queue.findIndex((t) => String(t.id) === String(currentId));
  nav.position = qi + 1;
  return nav;
}

export const needsReview = (s: ScanRecord) => s.result?.status === 'needs_review' || s.result?.status === 'failed';

/** Stable batch ordering: filename, then page. */
export function sortScans(scans: ScanRecord[]): ScanRecord[] {
  return [...scans].sort((a, b) => {
    const f = a.filename.localeCompare(b.filename, undefined, { numeric: true });
    if (f !== 0) return f;
    return (a.page ?? 0) - (b.page ?? 0);
  });
}
