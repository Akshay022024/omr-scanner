import { useId, useRef, useState, type DragEvent, type KeyboardEvent } from 'react';
import { ACCEPT_ATTR, MAX_FILES, MAX_FILE_BYTES } from '../lib/files';

interface Props {
  onFiles: (files: File[]) => void;
  disabled?: boolean;
}

export function Dropzone({ onFiles, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  const hintId = useId();

  const openPicker = () => {
    if (!disabled) inputRef.current?.click();
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(false);
    if (disabled) return;
    const files = Array.from(e.dataTransfer.files ?? []);
    if (files.length) onFiles(files);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openPicker();
    }
  };

  return (
    <div
      className={`dropzone${over ? ' dropzone--over' : ''}${disabled ? ' dropzone--disabled' : ''}`}
      role="button"
      tabIndex={disabled ? -1 : 0}
      aria-disabled={disabled}
      aria-describedby={hintId}
      aria-label="Add answer sheets: drop files here or press Enter to browse"
      onClick={openPicker}
      onKeyDown={onKeyDown}
      onDragEnter={(e) => {
        e.preventDefault();
        if (!disabled) setOver(true);
      }}
      onDragOver={(e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = disabled ? 'none' : 'copy';
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
        setOver(false);
      }}
      onDrop={onDrop}
    >
      <svg className="dropzone__icon" viewBox="0 0 24 24" width="36" height="36" aria-hidden="true">
        <path d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 15v3a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="dropzone__title">
        Drop answer sheets here or <span className="link-like">browse</span>
      </p>
      <p className="dropzone__hint" id={hintId}>
        JPG, PNG, TIFF, WebP or PDF · up to {MAX_FILE_BYTES / 1024 / 1024} MB each · max {MAX_FILES} files
      </p>
      <input
        ref={inputRef}
        type="file"
        multiple
        accept={ACCEPT_ATTR}
        hidden
        tabIndex={-1}
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = '';
          if (files.length) onFiles(files);
        }}
      />
    </div>
  );
}
