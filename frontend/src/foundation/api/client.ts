import axios, {
  type AxiosError,
  type AxiosRequestConfig,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import type { paths } from '@/api-schema'

// Module-level token variable - avoids circular dependency with auth store.
// Auth store calls setAccessToken() after login/refresh.
let _accessToken: string | null = null

export function setAccessToken(token: string | null): void {
  _accessToken = token
}

export function getAccessToken(): string | null {
  return _accessToken
}

export const API_BASE_URL = '/v1'

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true, // sends the httponly refresh_token cookie
})

// ── Request interceptor: attach Bearer token ──────────────────────────────
apiClient.interceptors.request.use((config) => {
  if (_accessToken) {
    config.headers.Authorization = `Bearer ${_accessToken}`
  }
  return config
})

// ── Token refresh ─────────────────────────────────────────────────────────
let refreshing: Promise<string> | null = null

/**
 * Exchange the httponly refresh cookie for a new access token and use it from
 * now on. Concurrent callers (requests that all hit an expired token, the
 * realtime event stream) share one refresh request.
 */
export function refreshAccessToken(): Promise<string> {
  refreshing ??= api
    .post('/auth/refresh')
    .then(({ data }) => {
      setAccessToken(data.access_token)
      return data.access_token
    })
    .finally(() => {
      refreshing = null
    })
  return refreshing
}

// ── Response interceptor: handle 401 + auto-refresh ──────────────────────
apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }

    // Only handle 401 on non-auth endpoints and non-retried requests.
    // Skip refresh for explicit credential failures (e.g. wrong current password) - these
    // are re-auth checks, not expired tokens, so refreshing would just retry and fail again.
    const errorCode = (error.response?.data as Record<string, unknown>)?.error_code
    if (
      error.response?.status === 401 &&
      !original._retry &&
      !original.url?.includes('/auth/') &&
      errorCode !== 'login_failed'
    ) {
      original._retry = true
      let token: string
      try {
        token = await refreshAccessToken()
      } catch (refreshError) {
        // Lazy import to avoid circular dep
        const { useAuthStore } = await import('@/foundation/stores/auth')
        useAuthStore().clearSession()
        window.location.href = '/login'
        return Promise.reject(refreshError)
      }
      original.headers.Authorization = `Bearer ${token}`
      return apiClient(original)
    }

    return Promise.reject(error)
  },
)

// ── Typed requests ───────────────────────────────────────────────────────
// `api.get('/roles/{identifier}', { path: { identifier: id } })` - the path,
// method, path params, body and response type are all checked against the
// generated API schema (`src/api-schema.ts`). Requests go through
// `apiClient`, so auth and token refresh work as above and errors are still
// AxiosErrors. Query params are not checked: list filters are dynamic
// `field__op` keys the schema cannot describe.

type Method = 'get' | 'post' | 'put' | 'patch' | 'delete'

/** API paths relative to the client's `/v1` base URL that support `M`. */
type PathFor<M extends Method> = {
  [P in keyof paths]: paths[P][M] extends undefined ? never : P extends `/v1${infer R}` ? R : never
}[keyof paths]

type Operation<P extends string, M extends Method> = NonNullable<paths[`/v1${P}` & keyof paths][M]>

type Content<T, Type extends string> = T extends { content: Record<Type, infer B> } ? B : never

/** Body of the success response; `void` for 204 No Content. */
type ResponseBody<O> = O extends { responses: infer R }
  ? {
      [C in keyof R & (200 | 201 | 202 | 204)]: [Content<R[C], 'application/json'>] extends [never]
        ? void
        : Content<R[C], 'application/json'>
    }[keyof R & (200 | 201 | 202 | 204)]
  : never

type RequestContent<O, Type extends string> = O extends { requestBody?: infer B }
  ? Content<NonNullable<B>, Type>
  : never

type PathParams<O> = O extends { parameters: { path: infer P } } ? P : never

type Part<Key extends string, T> = [T] extends [never] ? { [K in Key]?: never } : { [K in Key]: T }

/** A multipart body: binary fields (typed `string` by the schema) take a Blob. */
type Multipart<T> = [T] extends [never] ? never : { [K in keyof T]: T[K] | Blob }

type RequestOptions<O> = Part<'path', PathParams<O>> &
  Part<'body', RequestContent<O, 'application/json'>> &
  Part<'form', RequestContent<O, 'application/x-www-form-urlencoded'>> &
  Part<'multipart', Multipart<RequestContent<O, 'multipart/form-data'>>> & {
    query?: Record<string, string | number | boolean | null | undefined>
    config?: AxiosRequestConfig
  }

/** Options are optional only when the operation takes no path params or body. */
type OptionsArg<O> =
  Record<string, never> extends Omit<RequestOptions<O>, 'query' | 'config'>
    ? [options?: RequestOptions<O>]
    : [options: RequestOptions<O>]

function toFormData(fields: Record<string, string | Blob>): FormData {
  const data = new FormData()
  for (const [name, value] of Object.entries(fields)) data.append(name, value)
  return data
}

function request<M extends Method, P extends PathFor<M>>(
  method: M,
  path: P,
  ...[options]: OptionsArg<Operation<P, M>>
): Promise<AxiosResponse<ResponseBody<Operation<P, M>>>> {
  const {
    path: params,
    body,
    form,
    multipart,
    query,
    config,
  } = (options ?? {}) as {
    path?: Record<string, string | number>
    body?: unknown
    form?: Record<string, string>
    multipart?: Record<string, string | Blob>
    query?: Record<string, unknown>
    config?: AxiosRequestConfig
  }
  const url = path.replace(/\{(\w+)\}/g, (_, name: string) =>
    encodeURIComponent(String(params?.[name])),
  )
  return apiClient.request({
    ...config,
    method,
    url,
    params: query,
    // FormData sets its own multipart Content-Type (with the boundary).
    data: form ? new URLSearchParams(form) : multipart ? toFormData(multipart) : body,
    headers: form
      ? { ...config?.headers, 'Content-Type': 'application/x-www-form-urlencoded' }
      : config?.headers,
  })
}

export const api = {
  get: <P extends PathFor<'get'>>(path: P, ...options: OptionsArg<Operation<P, 'get'>>) =>
    request('get', path, ...options),
  post: <P extends PathFor<'post'>>(path: P, ...options: OptionsArg<Operation<P, 'post'>>) =>
    request('post', path, ...options),
  put: <P extends PathFor<'put'>>(path: P, ...options: OptionsArg<Operation<P, 'put'>>) =>
    request('put', path, ...options),
  patch: <P extends PathFor<'patch'>>(path: P, ...options: OptionsArg<Operation<P, 'patch'>>) =>
    request('patch', path, ...options),
  delete: <P extends PathFor<'delete'>>(path: P, ...options: OptionsArg<Operation<P, 'delete'>>) =>
    request('delete', path, ...options),
}
