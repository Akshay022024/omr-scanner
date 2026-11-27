/** Client-side upload checks mirroring the backend limits (ARCHITECTURE.md §7). */

export const MAX_FILE_BYTES = 20 * 1024 * 1024;
export const MAX_FILES = 50;
export const ACCEPTED_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.tif', '.tiff', '.webp', '.pdf'] as const;
export const ACCEPTED_MIME = ['image/jpeg', 'image/png', 'image/tiff', 'image/webp', 'application/pdf'] as const;
/** Value for <input type="file" accept>. */
export const ACCEPT_ATTR = [...ACCEPTED_EXTENSIONS, ...ACCEPTED_MIME].join(',');

export interface FileLike {
  name: string;
  size: number;
  type: string;
}

export function extensionOf(name: string): string {
  const i = name.lastIndexOf('.');
  return i >= 0 ? name.slice(i).toLowerCase() : '';
}

export function isAcceptedType(f: FileLike): boolean {
  const extOk = (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(f.name));
  // Some browsers report '' for TIFF; trust the extension then. A known-but-wrong MIME is rejected.
  const mimeOk = !f.type || (ACCEPTED_MIME as readonly string[]).includes(f.type);
  return extOk && mimeOk;
}

const fileKey = (f: FileLike) => `${f.name}::${f.size}`;

export interface FileSelection<T extends FileLike> {
  accepted: T[];
  rejected: { name: string; reason: string }[];
}

/** Merge newly picked files into the current selection, enforcing type, size, count and de-duplication. */
export function mergeFiles<T extends FileLike>(current: T[], incoming: T[]): FileSelection<T> {
  const accepted = [...current];
  const keys = new Set(current.map(fileKey));
  const rejected: { name: string; reason: string }[] = [];
  for (const f of incoming) {
    if (!isAcceptedType(f)) {
      rejected.push({ name: f.name, reason: 'unsupported type (JPG, PNG, TIFF, WebP or PDF only)' });
    } else if (f.size > MAX_FILE_BYTES) {
      rejected.push({ name: f.name, reason: `larger than ${MAX_FILE_BYTES / 1024 / 1024} MB` });
    } else if (f.size === 0) {
      rejected.push({ name: f.name, reason: 'empty file' });
    } else if (keys.has(fileKey(f))) {
      rejected.push({ name: f.name, reason: 'already added' });
    } else if (accepted.length >= MAX_FILES) {
      rejected.push({ name: f.name, reason: `limit of ${MAX_FILES} files per batch reached` });
    } else {
      accepted.push(f);
      keys.add(fileKey(f));
    }
  }
  return { accepted, rejected };
}
