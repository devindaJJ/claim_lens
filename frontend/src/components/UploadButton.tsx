import { useRef, useState, type DragEvent } from "react";
import { api } from "../api";

interface Props {
  onUploaded: () => void;
}

/** Upload button that also accepts PDFs dropped anywhere on it. */
export function UploadButton({ onUploaded }: Props) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function upload(files: FileList | File[]) {
    const pdfs = Array.from(files).filter((f) => f.type === "application/pdf" || f.name.toLowerCase().endsWith(".pdf"));
    if (pdfs.length === 0) {
      setError("Please choose PDF files.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      for (const file of pdfs) await api.upload(file);
      onUploaded();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
      if (input.current) input.current.value = "";
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    void upload(e.dataTransfer.files);
  }

  return (
    <div className="upload">
      <button
        type="button"
        className={`btn btn--primary${dragging ? " btn--dragging" : ""}`}
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        disabled={busy}
      >
        {busy ? "Uploading…" : "Upload claim"}
      </button>
      <input
        ref={input}
        type="file"
        accept="application/pdf"
        multiple
        hidden
        onChange={(e) => e.target.files && void upload(e.target.files)}
      />
      {error && (
        <span className="upload__error" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
