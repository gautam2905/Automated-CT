import type { Snapshot } from './types.gen'

export type ServerMessage =
  | { type: 'snapshot'; data: Snapshot }
  | { type: 'result'; id: number; ok: boolean; error: string | null }
  | { type: 'error'; message: string }

export interface Connection {
  send(obj: unknown): void
  close(): void
}

export function socketUrl(loc: Pick<Location, 'protocol' | 'host'> = window.location): string {
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws'
  return `${scheme}://${loc.host}/ws`
}

function parseMessage(raw: unknown): ServerMessage {
  try {
    const msg = JSON.parse(String(raw)) as ServerMessage
    if (msg && typeof msg === 'object' && 'type' in msg) return msg
  } catch {
    // fall through to the error message below
  }
  return { type: 'error', message: 'Unreadable message from the simulator' }
}

/** Opens the simulator socket. Sends made before it opens are queued and flushed on open. */
export function connect(
  onMessage: (msg: ServerMessage) => void,
  onClose: () => void,
  onOpen: () => void = () => {},
): Connection {
  const ws = new WebSocket(socketUrl())
  const queue: string[] = []
  ws.onopen = () => {
    queue.splice(0).forEach((text) => ws.send(text))
    onOpen()
  }
  ws.onmessage = (ev) => onMessage(parseMessage(ev.data))
  ws.onclose = () => onClose()
  ws.onerror = () => onMessage({ type: 'error', message: 'WebSocket error' })
  return {
    send(obj) {
      const text = JSON.stringify(obj)
      if (ws.readyState === WebSocket.OPEN) ws.send(text)
      else queue.push(text)
    },
    close() {
      ws.onclose = null
      ws.onerror = null
      ws.onmessage = null
      ws.close()
    },
  }
}
