import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Wraps the MediaRecorder API into start()/stop() -> Promise<Blob>.
 * Kept as a hook (not baked into Composer) so voice input can be reused
 * anywhere — e.g. a future "voice memo" attachment button.
 *
 * Robustness notes:
 *  - Permission is requested lazily on the first start() (browsers require a
 *    user gesture), and the resulting stream is reused for subsequent
 *    recordings so we don't re-prompt the user every time.
 *  - start() rejects with a friendly Error on denial / no device so the UI
 *    can surface it inline instead of throwing.
 *  - The stream's tracks are always stopped on stop()/cancel() so the mic
 *    indicator turns off and the browser can reclaim the device.
 */
export function useVoiceRecorder() {
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState(null);
  // Exposed reactively so a waveform visualizer can tap the live MediaStream
  // (an AnalyserNode) while recording. Null when not recording.
  const [stream, setStream] = useState(null);
  const [supported] = useState(
    () => typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia
  );
  const mediaRecorderRef = useRef(null);
  const chunksRef = useRef([]);
  const streamRef = useRef(null);

  const start = useCallback(async () => {
    if (!supported) {
      const err = new Error("Microphone is not supported in this browser.");
      setError(err);
      throw err;
    }
    if (recording) return;
    setError(null);
    try {
      // Reuse an existing live stream if we have one; otherwise request access.
      if (!streamRef.current || streamRef.current.getTracks().every((t) => !t.enabled)) {
        streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true });
      }
    } catch (err) {
      let message = "Couldn't access the microphone.";
      if (err && err.name === "NotAllowedError") {
        message =
          "Microphone permission was denied. Enable it in your browser's site settings, then try again.";
      } else if (err && err.name === "NotFoundError") {
        message = "No microphone was found on this device.";
      } else if (err && err.message) {
        message = err.message;
      }
      const friendly = new Error(message);
      setError(friendly);
      throw friendly;
    }

    const stream = streamRef.current;
    const recorder = new MediaRecorder(stream);
    chunksRef.current = [];
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };
    mediaRecorderRef.current = recorder;
    recorder.start();
    setStream(stream);
    setRecording(true);
  }, [recording, supported]);

  const stop = useCallback(() => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder) {
        setRecording(false);
        return resolve(null);
      }
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: "audio/webm" });
        // Release the mic so the OS indicator turns off between recordings.
        streamRef.current?.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setStream(null);
        setRecording(false);
        resolve(blob);
      };
      if (recorder.state !== "inactive") recorder.stop();
      else recorder.onstop();
    });
  }, []);

  const cancel = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder) recorder.onstop = null; // don't resolve stop() with a blob
    if (recorder && recorder.state !== "inactive") recorder.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    chunksRef.current = [];
    setStream(null);
    setRecording(false);
  }, []);

  // Clean up the stream if the component unmounts mid-recording.
  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  return { recording, error, supported, stream, start, stop, cancel };
}