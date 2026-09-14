import type { QueryClient, QueryKey } from "@tanstack/react-query";

const STORAGE_PREFIX = "repo-guard:sync-list:";

type SyncListState = {
  acceptedIds: number[];
};

export type SyncListStore = {
  read(key: string): string | null;
  write(key: string, value: string): void;
  remove(key: string): void;
  clearPrefix(prefix: string): void;
};

function memoryStore(): SyncListStore {
  const map = new Map<string, string>();
  return {
    read: (key) => map.get(key) ?? null,
    write: (key, value) => {
      map.set(key, value);
    },
    remove: (key) => {
      map.delete(key);
    },
    clearPrefix: (prefix) => {
      for (const key of [...map.keys()]) {
        if (key.startsWith(prefix)) {
          map.delete(key);
        }
      }
    },
  };
}

function sessionBackedStore(): SyncListStore {
  const mem = memoryStore();
  return {
    read(key) {
      const cached = mem.read(key);
      if (cached != null) {
        return cached;
      }
      try {
        const raw = sessionStorage.getItem(key);
        if (raw != null) {
          mem.write(key, raw);
        }
        return raw;
      } catch {
        return null;
      }
    },
    write(key, value) {
      mem.write(key, value);
      try {
        sessionStorage.setItem(key, value);
      } catch {
        // Private mode / quota — memory still holds the snapshot for this SPA session.
      }
    },
    remove(key) {
      mem.remove(key);
      try {
        sessionStorage.removeItem(key);
      } catch {
        // ignore
      }
    },
    clearPrefix(prefix) {
      mem.clearPrefix(prefix);
      try {
        const keys: string[] = [];
        for (let index = 0; index < sessionStorage.length; index += 1) {
          const key = sessionStorage.key(index);
          if (key?.startsWith(prefix)) {
            keys.push(key);
          }
        }
        for (const key of keys) {
          sessionStorage.removeItem(key);
        }
      } catch {
        // ignore
      }
    },
  };
}

function createDefaultStore(): SyncListStore {
  if (typeof sessionStorage === "undefined") {
    return memoryStore();
  }
  return sessionBackedStore();
}

let store: SyncListStore = createDefaultStore();

export function resetSyncListStoreForTests(next?: SyncListStore) {
  store = next ?? createDefaultStore();
}

function storageKey(queryKey: QueryKey): string {
  return `${STORAGE_PREFIX}${JSON.stringify(queryKey)}`;
}

function readState(queryKey: QueryKey): SyncListState | undefined {
  const raw = store.read(storageKey(queryKey));
  if (!raw) {
    return undefined;
  }
  try {
    const parsed = JSON.parse(raw) as SyncListState;
    if (!Array.isArray(parsed.acceptedIds)) {
      return undefined;
    }
    return parsed;
  } catch {
    return undefined;
  }
}

function writeState(queryKey: QueryKey, state: SyncListState) {
  store.write(storageKey(queryKey), JSON.stringify(state));
}

/** Record the ids from a successful Sync POST so later GETs cannot resurrect omitted rows. */
export function rememberSyncedIds<T extends { id: number }>(
  queryKey: QueryKey,
  items: T[],
) {
  writeState(queryKey, { acceptedIds: items.map((item) => item.id) });
}

/**
 * After a Sync in this session, GET lists are filtered to the last Sync `items`.
 * The backend upserts on sync and does not delete stale rows, so GET is a superset.
 */
export function reconcileFetchedList<T extends { id: number }>(
  queryKey: QueryKey,
  fetched: T[],
): T[] {
  const state = readState(queryKey);
  if (!state) {
    return fetched;
  }
  const accepted = new Set(state.acceptedIds);
  return fetched.filter((item) => accepted.has(item.id));
}

export function clearSyncListCache() {
  store.clearPrefix(STORAGE_PREFIX);
}

export async function applySyncedList<T extends { id: number }>(
  queryClient: QueryClient,
  queryKey: QueryKey,
  items: T[],
) {
  await queryClient.cancelQueries({ queryKey, exact: true });
  rememberSyncedIds(queryKey, items);
  queryClient.setQueryData(queryKey, items);
}
