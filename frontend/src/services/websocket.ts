export interface SocketMessage<T = unknown> {
  event: string
  payload: T
}

export interface SocketHandlers {
  onOpen?: () => void
  onClose?: () => void
  onError?: (event: Event) => void
  onMessage?: (message: SocketMessage) => void
}

interface ConnectSeasonSocketParams {
  seasonId: number
  userId: string
  baseUrl?: string
  handlers?: SocketHandlers
}

function toWsBaseUrl(baseUrl: string): string {
  if (baseUrl.startsWith('https://')) {
    return baseUrl.replace('https://', 'wss://')
  }
  if (baseUrl.startsWith('http://')) {
    return baseUrl.replace('http://', 'ws://')
  }
  return baseUrl
}

export function connectSeasonSocket(params: ConnectSeasonSocketParams): () => void {
  const rawBaseUrl = params.baseUrl ?? import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000'
  const wsBaseUrl = toWsBaseUrl(rawBaseUrl)
  const socket = new WebSocket(`${wsBaseUrl}/ws/${params.seasonId}/${params.userId}`)

  socket.onopen = () => {
    params.handlers?.onOpen?.()
  }

  socket.onerror = (event) => {
    params.handlers?.onError?.(event)
  }

  socket.onclose = () => {
    params.handlers?.onClose?.()
  }

  socket.onmessage = (event) => {
    try {
      const message = JSON.parse(event.data) as SocketMessage
      params.handlers?.onMessage?.(message)
    } catch {
      // Ignore malformed frames in mock stage.
    }
  }

  return () => {
    if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
      socket.close()
    }
  }
}
