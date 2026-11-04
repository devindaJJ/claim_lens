import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { useEffect, useRef, useState } from "react";

GlobalWorkerOptions.workerSrc = workerUrl;

const ZOOM_STEPS = [0.75, 1, 1.25, 1.5, 2];

/** Renders every page of a PDF to canvas with PDF.js, fitted to the pane width. */
export function PdfViewer({ url, title }: { url: string; title: string }) {
  const container = useRef<HTMLDivElement>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const task = getDocument(url);
    task.promise.then(setPdf, (e: Error) => setError(e.message));
    return () => void task.destroy();
  }, [url]);

  useEffect(() => {
    const el = container.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div className="pdf">
      <div className="pdf__toolbar">
        <span className="pdf__title" title={title}>{title}</span>
        {pdf && <span className="muted">{pdf.numPages} page{pdf.numPages > 1 ? "s" : ""}</span>}
        <div className="pdf__zoom">
          <button type="button" className="btn btn--ghost btn--sm" aria-label="Zoom out" disabled={zoom === ZOOM_STEPS[0]} onClick={() => setZoom(ZOOM_STEPS[ZOOM_STEPS.indexOf(zoom) - 1])}>−</button>
          <span className="pdf__zoom-value">{Math.round(zoom * 100)}%</span>
          <button type="button" className="btn btn--ghost btn--sm" aria-label="Zoom in" disabled={zoom === ZOOM_STEPS.at(-1)} onClick={() => setZoom(ZOOM_STEPS[ZOOM_STEPS.indexOf(zoom) + 1])}>+</button>
        </div>
        <a className="btn btn--ghost btn--sm" href={url} target="_blank" rel="noreferrer">Open original</a>
      </div>
      <div className="pdf__pages" ref={container}>
        {error && <div className="alert alert--error">Could not display the document: {error}</div>}
        {!pdf && !error && <div className="muted pdf__loading">Loading document…</div>}
        {pdf && width > 0 &&
          Array.from({ length: pdf.numPages }, (_, i) => (
            <PdfPage key={i} pdf={pdf} pageNumber={i + 1} width={(width - 32) * zoom} />
          ))}
      </div>
    </div>
  );
}

function PdfPage({ pdf, pageNumber, width }: { pdf: PDFDocumentProxy; pageNumber: number; width: number }) {
  const canvas = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    let cancelled = false;
    let render: { cancel: () => void } | undefined;
    void pdf.getPage(pageNumber).then((page) => {
      if (cancelled || !canvas.current) return;
      const base = page.getViewport({ scale: 1 });
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: (width / base.width) * ratio });
      const el = canvas.current;
      el.width = viewport.width;
      el.height = viewport.height;
      el.style.width = `${viewport.width / ratio}px`;
      el.style.height = `${viewport.height / ratio}px`;
      const task = page.render({ canvasContext: el.getContext("2d")!, viewport });
      render = task;
      task.promise.catch(() => undefined); // cancelled renders reject; ignore
    });
    return () => {
      cancelled = true;
      render?.cancel();
    };
  }, [pdf, pageNumber, width]);

  return <canvas ref={canvas} className="pdf__page" aria-label={`Page ${pageNumber}`} />;
}
