import { useEffect, useRef, useState } from "react";
import { useVoiceRecorder } from "../hooks/useVoiceRecorder";
import { api } from "../lib/api";
import Icon from "./Icon.jsx";
import VoiceRecordingPanel from "./VoiceRecordingPanel.jsx";

const KIND_ICON = { image: "image", video: "video", document: "file-text", audio: "headphones", other: "paperclip" };

const MODES = [
  { id: "off", icon: "message-circle", label: "Just chat", hint: "Answer from context — no search, no tools." },
  { id: "search", icon: "search", label: "Web search", hint: "Search the web for this message." },
  { id: "research", icon: "flask", label: "Deep Research", hint: "Multi-step investigation and a written report, instead of a quick answer." },
  { id: "agent", icon: "bot", label: "Agent", hint: "Cortex can run commands and read/write files across multiple steps.", requires: "agentAvailable" },
  { id: "council", icon: "users", label: "Council", hint: "Ask all your configured models at once, compare the answers.", requires: "councilAvailable" },
  { id: "image", icon: "image", label: "Image", hint: "Generate an image from your prompt with a local Stable Diffusion server.", requires: "imageAvailable" },
];

function ModePicker({ mode, setMode, agentAvailable, councilAvailable, imageAvailable }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const onClickOutside = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    const onEscape = (e) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onClickOutside);
    document.addEventListener("keydown", onEscape);
    return () => {
      document.removeEventListener("mousedown", onClickOutside);
      document.removeEventListener("keydown", onEscape);
    };
  }, [open]);

  const availability = { agentAvailable, councilAvailable, imageAvailable };
  const available = MODES.filter((m) => !m.requires || availability[m.requires]);
  const current = MODES.find((m) => m.id === mode) || MODES[0];

  return (
    <div className="mode-picker" ref={ref}>
      <button
        className={`mode-picker-btn ${mode !== "off" ? "is-active" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        title={current.hint}
      >
        <Icon name={current.icon} size={15} />
        <span className="mode-picker-label">{current.label}</span>
        <span className="mode-picker-caret" aria-hidden="true">
          <Icon name={open ? "chevron-up" : "chevron-down"} size={13} />
        </span>
      </button>
      {open && (
        <ul className="mode-picker-menu" role="listbox">
          {available.map((m) => (
            <li key={m.id}>
              <button
                className={`mode-picker-option ${m.id === mode ? "is-selected" : ""}`}
                role="option"
                aria-selected={m.id === mode}
                onClick={() => {
                  setMode(m.id);
                  setOpen(false);
                }}
              >
                <span className="mode-picker-option-icon" aria-hidden="true">
                  <Icon name={m.icon} size={15} />
                </span>
                <span>
                  <span className="mode-picker-option-label">{m.label}</span>
                  <span className="mode-picker-option-hint">{m.hint}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function Composer({
  onSend,
  onStop,
  disabled,
  conversationId = null,
  isStreaming = false,
  agentAvailable = false,
  councilAvailable = false,
  imageAvailable = false,
  onError = () => {},
  seedText = null,
}) {
  const [text, setText] = useState("");
  const [pending, setPending] = useState([]); // [{id, filename, kind, uploading}]
  const [transcribing, setTranscribing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [micError, setMicError] = useState(null);
  const [mode, setMode] = useState("off");
  const fileInputRef = useRef(null);
  const textareaRef = useRef(null);
  const { recording, error: recorderError, supported, stream, start, stop, cancel } = useVoiceRecorder();

  // Surface recorder errors inline (replaces the old alert()).
  useEffect(() => {
    if (recorderError) setMicError(recorderError.message);
  }, [recorderError]);

  // Seeded from a "quick action" on selected text elsewhere in the app
  // (BranchTree switches don't seed; only explicit quote/explain actions do).
  useEffect(() => {
    if (!seedText) return;
    setText((t) => (t ? `${t}\n${seedText.text}` : seedText.text));
    textareaRef.current?.focus();
  }, [seedText]);

  // Auto-grow textarea (Tier 6 #9)
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 200) + "px";
  }, [text]);

  const transcribeAndInsert = async (blob) => {
    if (!blob) return;
    setTranscribing(true);
    setMicError(null);
    try {
      const result = await api.transcribe(blob);
      setText((t) => (t ? `${t} ${result.text}` : result.text));
    } catch (err) {
      setMicError(`Transcription failed: ${err.message}`);
    } finally {
      setTranscribing(false);
    }
  };

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
        onError(`Upload failed: ${err.message}`);
      }
    }
  };

  const removeAttachment = (id) => setPending((p) => p.filter((a) => a.id !== id));

  const handleSend = () => {
    if (disabled) return;
    if (!text.trim() && pending.length === 0) return;
    if (pending.some((a) => a.uploading)) return;
    onSend(
      text.trim(),
      pending.map((a) => a.id),
      null,
      mode === "search",
      mode === "agent" && agentAvailable,
      mode === "research",
      null,
      mode === "council" && councilAvailable,
      mode === "image" && imageAvailable
    );
    setText("");
    setPending([]);
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // --- Microphone: push-to-talk (hold) is the primary interaction. ---
  // We deliberately do NOT also bind onClick to start/stop — doing both made
  // a single click start a recording, stop it, then start a second orphaned
  // recording. Hold = record, release = transcribe. A plain click toggles
  // record on/off for trackpad/touch users.
  const handleMicDown = async (e) => {
    e.preventDefault();
    if (recording) return;
    setMicError(null);
    try {
      await start();
    } catch {
      /* error is surfaced via recorderError -> micError */
    }
  };

  const handleMicUp = async (e) => {
    e.preventDefault();
    if (!recording) return;
    const blob = await stop();
    await transcribeAndInsert(blob);
  };

  const handleMicClick = async () => {
    // Only treat as a toggle if the pointer didn't already do a down/up cycle
    // (i.e. a genuine click without drag). Guard against double-triggering.
    if (recording) {
      const blob = await stop();
      await transcribeAndInsert(blob);
    } else {
      setMicError(null);
      try {
        await start();
      } catch {
        /* surfaced via micError */
      }
    }
  };

  const handleMicStopFromPanel = async () => {
    if (!recording) return;
    const blob = await stop();
    await transcribeAndInsert(blob);
  };

  const handleMicCancel = () => {
    cancel();
    setMicError(null);
  };

  // Spacebar hold-to-talk when the composer area is focused but the textarea
  // is not (Tier 3 #4).
  const handleComposerKeyDown = (e) => {
    if (e.code === "Space" && e.target !== textareaRef.current && !recording) {
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

  const micTitle = !supported
    ? "Microphone not supported"
    : recording
    ? "Release to stop (hold to talk)"
    : "Voice input — hold to talk, click to toggle";

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

      {micError && (
        <div className="composer-mic-error" role="alert">
          <span>{micError}</span>
          <button onClick={() => setMicError(null)} title="Dismiss">
            <Icon name="x" size={13} />
          </button>
        </div>
      )}

      {pending.length > 0 && (
        <div className="composer-attachments">
          {pending.map((a) => (
            <span className="attachment-chip" key={a.id}>
              <Icon name={a.uploading ? "hourglass" : KIND_ICON[a.kind] || "paperclip"} size={13} /> {a.filename}
              <button onClick={() => removeAttachment(a.id)} title="Remove">
                <Icon name="x" size={12} />
              </button>
            </span>
          ))}
        </div>
      )}

      {recording || transcribing ? (
        <VoiceRecordingPanel
          stream={stream}
          transcribing={transcribing}
          onStop={handleMicStopFromPanel}
          onCancel={handleMicCancel}
        />
      ) : (
      <div className="composer-row">
        <button
          className="composer-icon-btn"
          onClick={() => fileInputRef.current?.click()}
          title="Attach image, document, or video"
        >
          <Icon name="paperclip" size={17} />
        </button>
        <ModePicker
          mode={mode}
          setMode={setMode}
          agentAvailable={agentAvailable}
          councilAvailable={councilAvailable}
          imageAvailable={imageAvailable}
        />
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
              ? "Listening… release to stop"
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
            <Icon name="square" size={14} />
          </button>
        ) : (
          <button
            className={`composer-icon-btn mic-btn ${recording ? "mic-btn-active" : ""}`}
            onMouseDown={handleMicDown}
            onMouseUp={handleMicUp}
            onMouseLeave={() => recording && handleMicUp({ preventDefault() {} })}
            onClick={handleMicClick}
            disabled={!supported}
            title={micTitle}
          >
            <Icon name={recording ? "square" : "mic"} size={16} />
          </button>
        )}

        <button
          className="composer-send-btn"
          onClick={handleSend}
          disabled={disabled || (!text.trim() && pending.length === 0)}
          title="Send"
        >
          <Icon name="send" size={16} />
        </button>
      </div>
      )}
    </div>
  );
}
