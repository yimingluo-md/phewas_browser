/* Typed client for phewas_server API v1, with the per-launch bearer token. */
import type {
  DatasetInfo, DictionaryInfo, FsListing, GenePage, InspectAnnotation, InspectBundle, InspectSumstats, Job, Library,
  Meta, ProfileInfo, SearchResult, VariantPage,
} from "./types";

const TOKEN_KEY = "phewas.token";
let launchToken = "";

/** The token arrives once in the URL (?token=…) from the launcher; keep it out of the address bar. */
export function initToken(): void {
  const url = new URL(location.href);
  const t = url.searchParams.get("token");
  if (t) {
    launchToken = t;
    try { sessionStorage.setItem(TOKEN_KEY, t); localStorage.setItem(TOKEN_KEY, t); } catch { /* private mode */ }
    url.searchParams.delete("token");
    history.replaceState(null, "", url.pathname + url.search + url.hash);
  }
}

function token(): string {
  if (launchToken) return launchToken;
  try { return sessionStorage.getItem(TOKEN_KEY) ?? localStorage.getItem(TOKEN_KEY) ?? ""; } catch { return ""; }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token()}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const r = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail ?? detail; } catch { /* not json */ }
    throw new ApiError(r.status, typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json() as Promise<T>;
}

const get = <T>(path: string) => call<T>("GET", path);
const post = <T>(path: string, body?: unknown) => call<T>("POST", path, body ?? {});
const q = (s: string) => encodeURIComponent(s);

export const api = {
  health: () => get<{ application: string; status: string; version: string }>("/api/health"),
  library: () => get<Library>("/api/v1/library"),
  setCurrent: (id: string) => post<Library>("/api/v1/library/current", { id }),
  dataset: (id: string) => get<DatasetInfo>(`/api/v1/datasets/${q(id)}`),
  patchDataset: (id: string, body: { name?: string; notes?: string }) =>
    call<{ id: string; name: string; notes: string }>("PATCH", `/api/v1/datasets/${q(id)}`, body),
  deleteDataset: (id: string) => call<Library>("DELETE", `/api/v1/datasets/${q(id)}`),
  meta: (id: string) => get<Meta>(`/api/v1/datasets/${q(id)}/meta`),
  search: (id: string, term: string) => get<{ results: SearchResult[] }>(`/api/v1/datasets/${q(id)}/search?q=${q(term)}`),
  gene: (id: string, gene: string) => get<GenePage>(`/api/v1/datasets/${q(id)}/genes/${q(gene)}`),
  variant: (id: string, variant: string, gene: string | null) =>
    get<VariantPage>(`/api/v1/datasets/${q(id)}/variants/${q(variant)}${gene ? `?gene=${q(gene)}` : ""}`),
  profiles: () => get<ProfileInfo[]>("/api/v1/profiles"),
  dictionaries: () => get<DictionaryInfo[]>("/api/v1/dictionaries"),
  inspect: (body: { sumstats?: string; annotation?: string; profile?: string }) =>
    post<{ sumstats?: InspectSumstats; annotation?: InspectAnnotation }>("/api/v1/import/inspect", body),
  startImport: (body: Record<string, unknown>) => post<Job>("/api/v1/import/jobs", body),
  inspectBundle: (path: string) => post<InspectBundle>("/api/v1/import/inspect-bundle", { path }),
  importBundle: (body: { path: string; name?: string | null; make_current?: boolean }) => post<Job>("/api/v1/import/bundle", body),
  exportDataset: (id: string, path: string) => post<Job>(`/api/v1/datasets/${q(id)}/export`, { path }),
  jobs: () => get<Job[]>("/api/v1/jobs"),
  job: (id: string) => get<Job>(`/api/v1/jobs/${q(id)}`),
  cancelJob: (id: string) => post<Job>(`/api/v1/jobs/${q(id)}/cancel`),
  fs: (path?: string) => get<FsListing>(`/api/v1/fs${path ? `?path=${q(path)}` : ""}`),
};

/** Follow a job's SSE stream; resolves with the final snapshot. */
export function watchJob(id: string, onEvent: (j: Job) => void, after = 0, signal?: AbortSignal): Promise<Job> {
  return new Promise((resolve, reject) => {
    const es = new EventSource(`/api/v1/jobs/${q(id)}/events?after=${after}&token=${q(token())}`);
    let timer: number | undefined;
    let settled = false;
    const cleanup = () => { settled = true; es.close(); clearTimeout(timer); signal?.removeEventListener("abort", abort); };
    const abort = () => { cleanup(); reject(new DOMException("Navigation changed", "AbortError")); };
    signal?.addEventListener("abort", abort, { once: true });
    if (signal?.aborted) { abort(); return; }
    const receive = (job: Job) => {
      if (settled) return;
      onEvent(job);
      if (["done", "failed", "cancelled"].includes(job.status)) { cleanup(); resolve(job); }
    };
    const poll = async () => {
      try {
        receive(await api.job(id));
        if (!settled) timer = window.setTimeout(() => void poll(), 500);
      } catch (e) { if (!settled) { cleanup(); reject(e); } }
    };
    es.onmessage = (ev) => {
      const e = JSON.parse(ev.data);
      if (e.keepalive) return;
      receive(e as Job);
    };
    es.onerror = () => {
      es.close();
      if (!settled) void poll();
    };
  });
}
