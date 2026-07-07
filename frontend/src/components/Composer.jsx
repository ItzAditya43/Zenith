import { useEffect, useRef, useState } from "react";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";
import { api } from "../lib/api";

const KIND_ICON = { image: "🖼", video: "🎬", document: "📄", audio: "🎙", other: "📎" };

export default function Composer({ onSend, onStop, disabled, conversationId = null, isStreaming = false }) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState([]); // [{id, filename, kind, uploading}]
  const [transcribing, setTranscribing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const { recording, start, stop, cancel } = useVoiceRecorder();

  // Auto-grow textarea (Tier 6 #9)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);

  const handleFiles = async (files) => {
    for (const file of files) {
      const localId = `local-${Date.now()}-${file.name}`;
      setPending((p) => [...p, { id: localId, filename: file.name, kind: "other", uploading: true }]);
      try {
        const result = await api.upload(file, conversationId);
        setPending((p) =>
          p.map((a) => (a.id === localId ? { ...result, uploading: false } : a))
        );
      } catch (err) {
        setPending((p) => p.filter((a) => a.id !== localId));
        alert(`Upload failed: ${err.message}`);
      }
    }
  };

  const removeAttachment = (id) => setPending((p) => p.filter((a) => a.id !== id));

  const handleSend = () => {
    if (disabled) return;
    if (!text.trim() && pending.length === 0) return;
    if (pending.some((a) => a.uploading)) return;
    onSend(text.trim(), pending.map((a) => a.id));
    setText("");
    setPending([]);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  const handleMicClick = async () => {
    if (recording) {
      setTranscribing(true);
      const blob = await stop();
      try {
        const result = await api.transcribe(blob);
        setText((t) => (t ? `${t} ${result.text}` : result.text));
      } catch (err) {
        alert(`Transcription failed: ${err.message}`);
      } finally {
        setTranscribing(false);
      }
    } else {
      try {
        await start();
      } catch (err) {
        alert("Couldn't access microphone: " + err.message);
      }
    }
  };

  // Push-to-talk: hold mic button (Tier 3 #4)
  const handleMicDown = async (e) => {
    e.preventDefault();
    if (recording) return;
    try {
      await start();
    } catch (err) {
      alert("Couldn't access microphone: " + err.message);
    }
  };
  const handleMicUp = async (e) => {
    e.preventDefault();
    if (!recording) return;
    setTranscribing(true);
    const blob = await stop();
    try {
      const result = await api.transcribe(blob);
      setText((t) => (t ? `${t} ${result.text}` : result.text));
    } catch (err) {
      alert(`Transcription failed: ${err.message}`);
    } finally {
      setTranscribing(false);
    }
  };

  // Spacebar hold to talk when composer has focus (Tier 3 #4)
  const handleComposerKeyDown = (e) => {
    if (e.code === "Space" && e.target === textareaRef.current && !recording) {
      e.preventDefault();
      handleMicDown(e);
    }
  };
  const handleComposerKeyUp = (e) => {
    if (e.code === "Space" && recording) {
      e.preventDefault();
      handleMicUp(e);
    }
  };

  return (
    <div
      className={`composer ${dragging ? "composer-dragging" : ""}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (e.dataTransfer.files?.length) handleFiles(Array.from(e.dataTransfer.files));
      }}
      onKeyDown={handleComposerKeyDown}
      onKeyUp={handleComposerKeyUp}
    >
      {dragging && <div className="composer-drop-overlay">Drop files to attach</div>}
      {pending.length > 0 && (
        <div className="composer-attachments">
          {pending.map((a) => (
            <span className="attachment-chip" key={a.id}>
              {a.uploading ? "⏳" : KIND_ICON[a.kind] || "📎"} {a.filename}
              <button onClick={() => removeAttachment(a.id)} title="Remove">
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="composer-row">
        <button
          className="composer-icon-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Attach image, document, or video"
        >
          📎
        </button>
        <input
          ref={fileInputRef}
          type="file"
          multiple
          hidden
          onChange={(e) => {
            handleFiles(Array.from(e.target.files));
            e.target.value = "";
          }}
        />

        <textarea
          ref={textareaRef}
          className="composer-input"
          placeholder={
            recording
              ? "Recording… release to stop"
              : transcribing
              ? "Transcribing…"
              : "Message Cortex — attach files, or hold the mic to talk"
          }
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          disabled={transcribing}
        />

        {isStreaming ? (
          <button className="composer-send-btn stop-btn" onClick={onStop} title="Stop generating">
            ◼
          </button>
        ) : (
          <button
            className={`composer-icon-btn mic-btn ${recording ? "mic-btn-active" : ""}`}
            onMouseDown={handleMicDown}
            onMouseUp={handleMicUp}
            onMouseLeave={() => recording && handleMicUp({ preventDefault() {} })}
            onClick={handleMicClick}
            title={recording ? "Release to stop (hold to talk)" : "Voice input (hold)"}
          >
            {recording ? "◼" : "🎙"}
          </button>
        )}

        <button
          className="composer-send-btn"
          onClick={handleSend}
          disabled={disabled || (!text.trim() && pending.length === 0)}
          title="Send"
        >
          ➤
        </button>
      </div>
    </div>
  );
}