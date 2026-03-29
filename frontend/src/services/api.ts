const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'

export class ApiError extends Error {
  status: number

  constructor(message: string, status: number) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

async function request<T>(path: string, method: HttpMethod, body?: unknown, token?: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  })

  if (!response.ok) {
    let message = `Request failed: ${response.status}`
    try {
      const errorBody = (await response.json()) as { detail?: string; message?: string }
      if (errorBody?.detail) {
        message = errorBody.detail
      } else if (errorBody?.message) {
        message = errorBody.message
      }
    } catch {
      // Keep default message when response is not JSON.
    }
    throw new ApiError(message, response.status)
  }

  return (await response.json()) as T
}

export const api = {
  get: <T>(path: string, token?: string) => request<T>(path, 'GET', undefined, token),
  post: <T>(path: string, body?: unknown, token?: string) => request<T>(path, 'POST', body, token),
  put: <T>(path: string, body?: unknown, token?: string) => request<T>(path, 'PUT', body, token),
  patch: <T>(path: string, body?: unknown, token?: string) => request<T>(path, 'PATCH', body, token),
  delete: <T>(path: string, token?: string) => request<T>(path, 'DELETE', undefined, token),
}
