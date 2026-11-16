import { useCallback, useEffect, useRef, useState } from "react";

export type CameraStatus = "idle" | "starting" | "live" | "denied" | "unavailable" | "error";

/** Rear camera when available. The stream only starts after the learner has given recording consent. */
export function useCamera(enabled: boolean) {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [status, setStatus] = useState<CameraStatus>("idle");

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setStatus("idle");
  }, []);

  const start = useCallback(async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      setStatus("unavailable");
      return;
    }
    setStatus("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setStatus("live");
    } catch (e) {
      const name = (e as DOMException).name;
      setStatus(name === "NotAllowedError" ? "denied" : name === "NotFoundError" ? "unavailable" : "error");
    }
  }, []);

  useEffect(() => {
    if (enabled) void start();
    return stop;
  }, [enabled, start, stop]);

  /** Grab the current frame as a JPEG blob. */
  const capture = useCallback(async (): Promise<Blob | null> => {
    const v = videoRef.current;
    if (!v || status !== "live" || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    const scale = Math.min(1, 1280 / v.videoWidth);
    c.width = Math.round(v.videoWidth * scale);
    c.height = Math.round(v.videoHeight * scale);
    c.getContext("2d")!.drawImage(v, 0, 0, c.width, c.height);
    return new Promise((res) => c.toBlob((b) => res(b), "image/jpeg", 0.85));
  }, [status]);

  return { videoRef, status, start, stop, capture };
}
