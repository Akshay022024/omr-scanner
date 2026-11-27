import { createHttpClient, type ApiClient } from './client';
import { createMockClient } from './mock';

export * from './types';
export type { ApiClient, UploadProgress, UploadRequest } from './client';
export { ApiError, errorMessage } from './errors';

export const USE_MOCKS = import.meta.env.VITE_USE_MOCKS === 'true';

/** The app-wide API client: in-memory fixtures when VITE_USE_MOCKS=true, otherwise the real backend via /api. */
export const api: ApiClient = USE_MOCKS ? createMockClient() : createHttpClient({ baseUrl: '/api' });
