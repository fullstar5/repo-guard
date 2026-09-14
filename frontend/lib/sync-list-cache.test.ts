import assert from "node:assert/strict";
import { afterEach, test } from "node:test";

import {
  clearSyncListCache,
  reconcileFetchedList,
  rememberSyncedIds,
  resetSyncListStoreForTests,
} from "./sync-list-cache";

const reposKey = ["repositories"];

afterEach(() => {
  clearSyncListCache();
  resetSyncListStoreForTests();
});

test("GET list is unchanged before any Sync", () => {
  const fetched = [{ id: 1 }, { id: 2 }, { id: 3 }];
  assert.deepEqual(reconcileFetchedList(reposKey, fetched), fetched);
});

test("after Sync, GET extras (deleted leftover rows) stay hidden", () => {
  rememberSyncedIds(reposKey, [{ id: 1 }, { id: 2 }]);
  assert.deepEqual(reconcileFetchedList(reposKey, [{ id: 1 }, { id: 2 }, { id: 3 }]), [
    { id: 1 },
    { id: 2 },
  ]);
});

test("empty Sync hides the entire GET list", () => {
  rememberSyncedIds(reposKey, []);
  assert.deepEqual(reconcileFetchedList(reposKey, [{ id: 8 }, { id: 9 }]), []);
});

test("a later Sync can restore a previously omitted id", () => {
  rememberSyncedIds(reposKey, [{ id: 1 }]);
  rememberSyncedIds(reposKey, [{ id: 1 }, { id: 3 }]);
  assert.deepEqual(reconcileFetchedList(reposKey, [{ id: 1 }, { id: 2 }, { id: 3 }]), [
    { id: 1 },
    { id: 3 },
  ]);
});

test("snapshots are isolated per query key", () => {
  const prKey = ["repositories", 4, "pull-requests"];
  rememberSyncedIds(reposKey, [{ id: 1 }]);
  rememberSyncedIds(prKey, [{ id: 10 }, { id: 11 }]);
  assert.deepEqual(reconcileFetchedList(reposKey, [{ id: 1 }, { id: 2 }]), [{ id: 1 }]);
  assert.deepEqual(reconcileFetchedList(prKey, [{ id: 10 }, { id: 11 }, { id: 12 }]), [
    { id: 10 },
    { id: 11 },
  ]);
});

test("clearing the cache returns GET to the unfiltered list", () => {
  rememberSyncedIds(reposKey, [{ id: 1 }]);
  clearSyncListCache();
  const fetched = [{ id: 1 }, { id: 2 }];
  assert.deepEqual(reconcileFetchedList(reposKey, fetched), fetched);
});
