import { useEffect, useRef, useState } from "react";
import { wsUrl } from "../api/client";

/** Calls onMessage for every server push. Reconnects with backoff; reports connection state. */
export function useSessionSocket(sessionId: string | undefined, onMessage: (msg: unknown) => void) {
  const [connected, setConnected] = useState(false);
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    if (!sessionId) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let ping: ReturnType<typeof setInterval> | undefined;
    let retry: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      ws = new WebSocket(wsUrl(`/sessions/${sessionId}/ws`));
      ws.onopen = () => {
        attempt = 0;
        setConnected(true);
        ping = setInterval(() => ws?.readyState === WebSocket.OPEN && ws.send("ping"), 25_000);
      };
      ws.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data));
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = (e) => {
        setConnected(false);
        clearInterval(ping);
        if (closed || e.code === 4401 || e.code === 4404) return;
        retry = setTimeout(connect, Math.min(15_000, 1000 * 2 ** attempt++));
      };
    };
    connect();
    return () => {
      closed = true;
      clearInterval(ping);
      clearTimeout(retry);
      ws?.close();
    };
  }, [sessionId]);

  return connected;
}
