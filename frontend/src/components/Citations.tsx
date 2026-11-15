import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { research, type DocRef } from "../lib/api";

/** Every claim in a dossier carries chips like "D2 p5". Tapping one opens the
 *  page's text right here, with a link to the original exchange PDF. */

type Open = (docId: string, page: number) => void;
const Ctx = createContext<{ open: Open; docs: Record<string, DocRef> }>({ open: () => {}, docs: {} });

export function CitationProvider({ docs, children }: { docs: DocRef[]; children: ReactNode }) {
  const [cur, setCur] = useState<{ docId: string; page: number } | null>(null);
  const byRef = Object.fromEntries(docs.map((d) => [d.ref, d]));
  return (
    <Ctx.Provider value={{ open: (docId, page) => setCur({ docId, page }), docs: byRef }}>
      {children}
      {cur && <PageSheet docId={cur.docId} page={cur.page} doc={docs.find((d) => d.id === cur.docId)} onClose={() => setCur(null)} />}
    </Ctx.Provider>
  );
}

/** Accepts "D2:p5", "FIN", or {ref, page}. */
export function Cite({ tag, refName, page }: { tag?: string; refName?: string | null; page?: number | null }) {
  const { open, docs } = useContext(Ctx);
  let r = refName ?? undefined, p = page ?? undefined;
  if (tag) {
    if (tag === "FIN") return <span className="ml-1 text-[11.5px] font-semibold text-muted bg-wash rounded px-1.5 py-px align-[1px]" title="Figures computed from the results filings in the table">results table</span>;
    const m = tag.match(/^D(\d+):p(\d+)$/);
    if (m) { r = `D${m[1]}`; p = Number(m[2]); }
  }
  const d = r ? docs[r] : undefined;
  if (!d || !p) return null;
  return (
    <button onClick={() => open(d.id, p!)} title={`${kindLabel(d.kind)} ${d.period_label ?? ""}, page ${p}`}
            className="ml-1 text-[11.5px] font-semibold text-accent bg-accent-wash rounded px-1.5 py-px align-[1px] hover:underline">
      {r} p{p}
    </button>
  );
}

export function kindLabel(k: string) {
  return k === "results" ? "Results filing" : k === "transcript" ? "Concall transcript" : k === "presentation" ? "Investor presentation" : "Filing";
}

function PageSheet({ docId, page, doc, onClose }: { docId: string; page: number; doc?: DocRef; onClose: () => void }) {
  const [text, setText] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { research.page(docId, page).then((r) => setText(r.text)).catch((e) => setErr(e.message)); }, [docId, page]);
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50" role="dialog" aria-modal="true" aria-label="Source page">
      <button className="absolute inset-0 bg-ink/30" aria-label="Close" onClick={onClose} />
      <div className="absolute inset-x-0 bottom-0 sm:inset-y-0 sm:left-auto sm:right-0 sm:w-[520px] max-h-[85dvh] sm:max-h-none bg-surface rounded-t-xl sm:rounded-none border-l border-rule flex flex-col">
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-rule">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold">{doc ? `${doc.ref}: ${kindLabel(doc.kind)}${doc.period_label ? `, ${doc.period_label}` : ""}` : "Source"}</div>
            <div className="text-[12.5px] text-muted">Page {page}{doc?.pages ? ` of ${doc.pages}` : ""}, text as extracted from the PDF</div>
          </div>
          <button onClick={onClose} className="text-accent font-semibold text-[14.5px] shrink-0">Done</button>
        </div>
        <div className="flex-1 overflow-y-auto px-4 py-3">
          {err && <p className="text-down text-[14px]">{err}</p>}
          {text == null && !err && <p className="text-muted text-[14px]">Loading page…</p>}
          {text != null && <pre className="whitespace-pre-wrap font-sans text-[13.5px] leading-relaxed text-ink">{text.trim() || "(No text layer on this page. It's a scanned image; open the PDF.)"}</pre>}
        </div>
        {doc && (
          <div className="px-4 py-3 border-t border-rule">
            <a href={doc.url} target="_blank" rel="noreferrer" className="font-semibold text-accent underline underline-offset-2 text-[14px]">
              Open the original PDF on NSE
            </a>
            <span className="text-[12.5px] text-muted">, then go to page {page}</span>
          </div>
        )}
      </div>
    </div>
  );
}
