/* App-wide state: the library, the dataset in view, per-dataset metadata cache. */
import { api } from "./api";
import type { Library, LibraryEntry, Meta } from "./types";

let library: Library | null = null;
const metaCache = new Map<string, Meta>();
let activeDataset: string | null = null;
const listeners = new Set<() => void>();

export function onChange(fn: () => void): void { listeners.add(fn); }
function emit(): void { listeners.forEach((fn) => fn()); }

export async function loadLibrary(force = false): Promise<Library> {
  if (!library || force) {
    library = await api.library();
    emit();
  }
  return library;
}
export function getLibrary(): Library | null { return library; }
export function invalidateLibrary(): void { library = null; metaCache.clear(); }

export function datasetEntry(id: string | null): LibraryEntry | null {
  return library?.datasets.find((d) => d.id === id) ?? null;
}

export function setActive(id: string | null): void {
  if (activeDataset !== id) { activeDataset = id; emit(); }
}
export function active(): string | null { return activeDataset; }

export async function loadMeta(id: string): Promise<Meta> {
  let m = metaCache.get(id);
  if (!m) { m = await api.meta(id); metaCache.set(id, m); }
  return m;
}
export function dropMeta(id: string): void { metaCache.delete(id); }

/** The id to use when a route has none: the library's current dataset. */
export async function defaultDataset(): Promise<string | null> {
  const lib = await loadLibrary();
  return lib.current ?? lib.datasets[0]?.id ?? null;
}
