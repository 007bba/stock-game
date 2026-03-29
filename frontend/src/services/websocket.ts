export interface SocketMessage<T = unknown> {
  event: string
  sequence?: number
  serverTime?: string
  payload: T
}

export interface SocketHandlers {
  onOpen?: () => void
  onClose?: () => void
  onError?: (event: Event) => void
  onMessage?: (message: SocketMessage) => void
  onReconnectAttempt?: (attempt: number, maxAttempts: number) => void
  onReconnectExhausted?: (maxAttempts: number) => void
}

interface WebSocketClientOptions {
  maxReconnectAttempts?: number
  heartbeatMs?: number
  baseReconnectDelayMs?: number
  maxReconnectDelayMs?: number
}

interface ConnectSeasonSocketParams {
  seasonId: number
  token: string
  baseUrl?: string
  handlers?: SocketHandlers
  options?: WebSocketClientOptions
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

export function createSeasonSocketUrl(params: { seasonId: number; token: string; baseUrl?: string }): string {
  const rawBaseUrl = params.baseUrl ?? import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000'
  const wsBaseUrl = toWsBaseUrl(rawBaseUrl)
  const token = encodeURIComponent(params.token)
  return `${wsBaseUrl}/ws/${params.seasonId}?token=${token}`
}

export class WebSocketClient {
  private socket: WebSocket | null = null
  private reconnectAttempts = 0
  private reconnectTimer: number | null = null
  private heartbeatTimer: number | null = null
  private manualClose = false

  private readonly url: string
  private readonly handlers: SocketHandlers

  private readonly maxReconnectAttempts: number
  private readonly heartbeatMs: number
  private readonly baseReconnectDelayMs: number
  private readonly maxReconnectDelayMs: number

  constructor(url: string, handlers: SocketHandlers = {}, options: WebSocketClientOptions = {}) {
    this.url = url
    this.handlers = handlers
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 5
    this.heartbeatMs = options.heartbeatMs ?? 30000
    this.baseReconnectDelayMs = options.baseReconnectDelayMs ?? 1000
    this.maxReconnectDelayMs = options.maxReconnectDelayMs ?? 30000
  }

  connect(): void {
    this.manualClose = false
    this.openSocket()
  }

  disconnect(): void {
    this.manualClose = true
    this.clearReconnectTimer()
    this.stopHeartbeat()

    if (this.socket && (this.socket.readyState === WebSocket.OPEN || this.socket.readyState === WebSocket.CONNECTING)) {
      this.socket.close()
    }
    this.socket = null
  }

  sendText(payload: string): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(payload)
    }
  }

  private openSocket(): void {
    this.clearReconnectTimer()
    this.socket = new WebSocket(this.url)

    this.socket.onopen = () => {
      this.reconnectAttempts = 0
      this.startHeartbeat()
      this.handlers.onOpen?.()
    }

    this.socket.onerror = (event) => {
      this.handlers.onError?.(event)
    }

    this.socket.onclose = () => {
      this.stopHeartbeat()
      this.handlers.onClose?.()

      if (this.manualClose) {
        return
      }

      this.scheduleReconnect()
    }

    this.socket.onmessage = (event) => {
      if (typeof event.data !== 'string') {
        return
      }

      const text = event.data.trim()
      if (!text) {
        return
      }

      if (text === 'ping') {
        this.sendText('pong')
        return
      }
      if (text === 'pong') {
        return
      }

      try {
        const message = JSON.parse(text) as SocketMessage
        this.handlers.onMessage?.(message)
      } catch {
        // Ignore malformed frames.
      }
    }
  }

  private startHeartbeat(): void {
    this.stopHeartbeat()
    this.heartbeatTimer = window.setInterval(() => {
      this.sendText('ping')
    }, this.heartbeatMs)
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer !== null) {
      window.clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      this.handlers.onReconnectExhausted?.(this.maxReconnectAttempts)
      return
    }

    this.reconnectAttempts += 1
    this.handlers.onReconnectAttempt?.(this.reconnectAttempts, this.maxReconnectAttempts)

    const delay = Math.min(
      this.baseReconnectDelayMs * 2 ** (this.reconnectAttempts - 1),
      this.maxReconnectDelayMs,
    )

    this.reconnectTimer = window.setTimeout(() => {
      this.openSocket()
    }, delay)
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      window.clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }
}

export function connectSeasonSocket(params: ConnectSeasonSocketParams): () => void {
  const url = createSeasonSocketUrl({
    seasonId: params.seasonId,
    token: params.token,
    baseUrl: params.baseUrl,
  })

  const client = new WebSocketClient(url, params.handlers, params.options)
  client.connect()

  return () => {
    client.disconnect()
  }
}
