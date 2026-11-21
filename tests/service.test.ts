import assert from "node:assert/strict";
import test from "node:test";
import { LeaderboardService } from "../src/service.js";
import { MemoryStore } from "../src/store.js";
import { TABLES, type Clock, type ScoreInput } from "../src/types.js";

class FakeClock implements Clock {
  constructor(private value: Date) {}
  now(): Date {
    return new Date(this.value);
  }
  set(value: string): void {
    this.value = new Date(value);
  }
}

async function setup() {
  const clock = new FakeClock(new Date("2026-11-19T15:30:00Z"));
  const service = new LeaderboardService(new MemoryStore(), clock);
  const definition = await service.createLeaderboard({
    name: "薄肌教练排行榜",
    timezone: "Asia/Shanghai",
    creator_subject: "creator"
  });
  const leaderboardId = String(definition.leaderboard_id);
  await service.join({ leaderboard_id: leaderboardId, member_subject: "alice", display_name: "Alice" });
  return { service, clock, leaderboardId, definition };
}

function scores(definition: Record<string, unknown>, values = [80, 70, 75]): ScoreInput[] {
  const dimensions = definition.dimensions as Array<Record<string, unknown>>;
  return dimensions.map((dimension, index) => ({
    dimension_id: String(dimension.dimension_id),
    criteria_version_id: String(dimension.criteria_version_id),
    score: values[index]
  }));
}

test("confirmed defaults include 50/50, rest-day 60, and risk cap 50", async () => {
  const { definition } = await setup();
  assert.equal(definition.current_local_date, "2026-11-19");
  const dimensions = definition.dimensions as Array<Record<string, unknown>>;
  assert.deepEqual(dimensions.map((item) => item.dimension_id), ["diet", "exercise", "thin-muscle"]);
  assert.match(String(dimensions.find((item) => item.dimension_id === "exercise")?.criteria_text), /休息日默认 60/);
  assert.match(String(dimensions.find((item) => item.dimension_id === "thin-muscle")?.criteria_text), /50% \+ 运动分 50%/);
  for (const dimension of dimensions) assert.match(String(dimension.criteria_text), /最高 50 分/);
});

test("server timezone chooses the date and same-day updates overwrite the final snapshot", async () => {
  const { service, leaderboardId, definition } = await setup();
  const first = await service.submitDailyUpdate({
    leaderboard_id: leaderboardId,
    member_subject: "alice",
    idempotency_key: "alice-1",
    scores: scores(definition)
  });
  assert.equal(first.local_date, "2026-11-19");
  assert.equal(first.overwritten, false);

  const retry = await service.submitDailyUpdate({
    leaderboard_id: leaderboardId,
    member_subject: "alice",
    idempotency_key: "alice-1",
    scores: scores(definition)
  });
  assert.equal(retry.idempotent, true);

  const replacement = await service.submitDailyUpdate({
    leaderboard_id: leaderboardId,
    member_subject: "alice",
    idempotency_key: "alice-2",
    scores: scores(definition, [90, 80, 85])
  });
  assert.equal(replacement.overwritten, true);
  const daily = await service.getLeaderboard({ leaderboard_id: leaderboardId, period: "day" });
  assert.equal((daily.entries as Array<Record<string, unknown>>)[0].score, 85);
});

test("reusing an idempotency key with different scores is rejected", async () => {
  const { service, leaderboardId, definition } = await setup();
  await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "same", scores: scores(definition) });
  await assert.rejects(
    () => service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "same", scores: scores(definition, [1, 2, 3]) }),
    /already used/
  );
});

test("weekly leaderboard sums each day's final score instead of averaging", async () => {
  const { service, clock, leaderboardId, definition } = await setup();
  await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "d1", scores: scores(definition, [80, 60, 70]) });
  clock.set("2026-11-20T15:30:00Z");
  const nextDefinition = await service.getDefinition({ leaderboard_id: leaderboardId });
  await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "d2", scores: scores(nextDefinition, [100, 80, 90]) });
  const weekly = await service.getLeaderboard({ leaderboard_id: leaderboardId, period: "week" });
  assert.equal((weekly.entries as Array<Record<string, unknown>>)[0].score, 160);
  assert.equal(weekly.scoring, "sum_of_each_day_final_score");
  const entry = (weekly.entries as Array<Record<string, unknown>>)[0];
  assert.equal(entry.display_name, "Alice");
  assert.equal("member_subject" in entry, false);
});

test("criteria updates and added dimensions take effect next cycle only", async () => {
  const { service, clock, leaderboardId } = await setup();
  const update = await service.updateCriteria({
    leaderboard_id: leaderboardId,
    actor_subject: "creator",
    dimension_id: "diet",
    criteria_text: "新版饮食标准"
  });
  assert.equal(update.effective_from_cycle, "2026-11-23");
  const added = await service.addDimension({
    leaderboard_id: leaderboardId,
    actor_subject: "creator",
    dimension_id: "recovery",
    name: "恢复分",
    description: "恢复计划执行情况",
    criteria_text: "按恢复计划执行情况给 0–100 分"
  });
  assert.equal(added.effective_from_cycle, "2026-11-23");
  const before = await service.getDefinition({ leaderboard_id: leaderboardId });
  assert.equal((before.dimensions as Array<Record<string, unknown>>).length, 3);
  clock.set("2026-11-23T01:00:00Z");
  const after = await service.getDefinition({ leaderboard_id: leaderboardId });
  const dimensions = after.dimensions as Array<Record<string, unknown>>;
  assert.equal(dimensions.length, 4);
  assert.equal(dimensions.find((item) => item.dimension_id === "diet")?.criteria_text, "新版饮食标准");
});

test("only creator can mutate definition and leaving blocks submissions", async () => {
  const { service, leaderboardId, definition } = await setup();
  await assert.rejects(
    () => service.updateCriteria({ leaderboard_id: leaderboardId, actor_subject: "alice", dimension_id: "diet", criteria_text: "nope" }),
    /Only the leaderboard creator/
  );
  await service.leave({ leaderboard_id: leaderboardId, member_subject: "alice" });
  await assert.rejects(
    () => service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "left", scores: scores(definition) }),
    /has not joined/
  );
});

test("submissions require all active dimensions and current criteria versions", async () => {
  const { service, leaderboardId, definition } = await setup();
  await assert.rejects(
    () => service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "partial", scores: scores(definition).slice(0, 2) }),
    /STALE_CRITERIA: submitted dimensions do not match the current definition/
  );
  const stale = scores(definition);
  stale[0].criteria_version_id = "stale";
  await assert.rejects(
    () => service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "stale", scores: stale }),
    /^Error: STALE_CRITERIA: diet must use the current definition; refresh and recalculate all scores$/
  );
});

test("a cached definition becomes stale at the cycle boundary and succeeds after refresh", async () => {
  const { service, clock, leaderboardId, definition: cachedDefinition } = await setup();
  assert.equal(cachedDefinition.current_cycle_start, "2026-11-16");
  assert.equal(cachedDefinition.next_cycle_start, "2026-11-23");
  await service.updateCriteria({
    leaderboard_id: leaderboardId,
    actor_subject: "creator",
    dimension_id: "diet",
    criteria_text: "新周期饮食标准"
  });
  clock.set("2026-11-23T01:00:00Z");

  await assert.rejects(
    () => service.submitDailyUpdate({
      leaderboard_id: leaderboardId,
      member_subject: "alice",
      idempotency_key: "cached-old-cycle",
      scores: scores(cachedDefinition)
    }),
    /STALE_CRITERIA: diet must use the current definition/
  );

  const refreshed = await service.getDefinition({ leaderboard_id: leaderboardId });
  assert.equal(refreshed.current_cycle_start, "2026-11-23");
  assert.equal(refreshed.next_cycle_start, "2026-11-30");
  const accepted = await service.submitDailyUpdate({
    leaderboard_id: leaderboardId,
    member_subject: "alice",
    idempotency_key: "refreshed-new-cycle",
    scores: scores(refreshed)
  });
  assert.equal(accepted.local_date, "2026-11-23");
});

/** Shares one MemoryStore and can fail the next create or hold every list until N callers are waiting. */
class ControlledStore extends MemoryStore {
  failNextCreate = false;
  private barrier?: { size: number; waiting: Array<() => void> };

  holdLists(size: number): void {
    this.barrier = { size, waiting: [] };
  }

  override async list(table: Parameters<MemoryStore["list"]>[0]) {
    const barrier = this.barrier;
    if (barrier && table === "DailyScores") {
      await new Promise<void>((resolve) => {
        barrier.waiting.push(resolve);
        if (barrier.waiting.length >= barrier.size) {
          this.barrier = undefined;
          barrier.waiting.forEach((release) => release());
        }
      });
    }
    return super.list(table);
  }

  override async create(table: Parameters<MemoryStore["create"]>[0], fields: Record<string, unknown>) {
    if (this.failNextCreate && table === "DailyScores") {
      this.failNextCreate = false;
      throw new Error("simulated Base failure");
    }
    return super.create(table, fields);
  }
}

async function setupControlled() {
  const store = new ControlledStore();
  const clock = new FakeClock(new Date("2026-11-19T15:30:00Z"));
  const service = new LeaderboardService(store, clock);
  const definition = await service.createLeaderboard({ name: "榜", timezone: "Asia/Shanghai", creator_subject: "creator" });
  const leaderboardId = String(definition.leaderboard_id);
  await service.join({ leaderboard_id: leaderboardId, member_subject: "alice", display_name: "Alice" });
  const dayScore = async () =>
    ((await service.getLeaderboard({ leaderboard_id: leaderboardId, period: "day" })).entries as Array<Record<string, unknown>>)[0]?.score;
  return { store, clock, service, definition, leaderboardId, dayScore };
}

test("a failed write leaves the previous snapshot whole and a same-key retry completes the new one", async () => {
  const { store, service, definition, leaderboardId, dayScore } = await setupControlled();
  await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "a", scores: scores(definition, [80, 70, 75]) });
  store.failNextCreate = true;
  await assert.rejects(
    () => service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "b", scores: scores(definition, [90, 80, 85]) }),
    /simulated Base failure/
  );
  assert.equal(await dayScore(), 75);
  const diet = ((await service.getLeaderboard({ leaderboard_id: leaderboardId, period: "day", dimension_id: "diet" })).entries as Array<Record<string, unknown>>)[0].score;
  assert.equal(diet, 80, "no dimension of the failed submission was written");
  const retry = await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "b", scores: scores(definition, [90, 80, 85]) });
  assert.equal(retry.idempotent, false);
  assert.equal(await dayScore(), 85);
});

test("concurrent first submissions from separate instances never double count a day", async () => {
  const { store, service, definition, leaderboardId, dayScore } = await setupControlled();
  store.holdLists(2);
  await Promise.all([
    service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "x", scores: scores(definition, [80, 70, 75]) }),
    service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "y", scores: scores(definition, [80, 70, 75]) })
  ]);
  assert.equal((await store.list(TABLES.dailyScores)).length, 2, "both writers appended");
  assert.equal(await dayScore(), 75, "the ranking uses one final snapshot");
  const week = ((await service.getLeaderboard({ leaderboard_id: leaderboardId, period: "week" })).entries as Array<Record<string, unknown>>)[0].score;
  assert.equal(week, 75);
});

test("concurrent same-key retries count once and later retries stay idempotent", async () => {
  const { store, service, definition, leaderboardId, dayScore } = await setupControlled();
  store.holdLists(2);
  const input = { leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "same", scores: scores(definition, [80, 70, 75]) };
  await Promise.all([service.submitDailyUpdate(input), service.submitDailyUpdate(input)]);
  assert.equal(await dayScore(), 75);
  assert.equal((await service.submitDailyUpdate(input)).idempotent, true);
});

test("a replay of an older submission never overwrites a newer final snapshot", async () => {
  const { clock, service, definition, leaderboardId, dayScore } = await setupControlled();
  const a = { leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "A", scores: scores(definition, [80, 70, 75]) };
  await service.submitDailyUpdate(a);
  clock.set("2026-11-19T15:31:00Z");
  await service.submitDailyUpdate({ leaderboard_id: leaderboardId, member_subject: "alice", idempotency_key: "B", scores: scores(definition, [90, 80, 85]) });
  clock.set("2026-11-19T15:32:00Z");
  const replay = await service.submitDailyUpdate(a);
  assert.equal(replay.idempotent, true);
  assert.equal(await dayScore(), 85);
  await assert.rejects(() => service.submitDailyUpdate({ ...a, scores: scores(definition, [1, 2, 3]) }), /already used with different scores/);
});
