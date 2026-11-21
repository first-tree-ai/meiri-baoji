import { createHash, randomUUID } from "node:crypto";
import { DEFAULT_DIMENSIONS } from "./default-policy.js";
import { addDays, cycleStart, inCycle, localDate, nextCycleStart } from "./time.js";
import {
  TABLES,
  type Clock,
  type RecordStore,
  type ScoreInput,
  type StoredRecord,
  systemClock
} from "./types.js";

function text(value: unknown): string {
  if (typeof value === "string") return value;
  if (Array.isArray(value) && typeof value[0] === "string") return value[0];
  return "";
}

function number(value: unknown): number {
  return typeof value === "number" ? value : Number(value);
}

function required(value: string, label: string): string {
  const result = value.trim();
  if (!result) throw new Error(`${label} is required`);
  return result;
}

function assertTimezone(timezone: string): void {
  try {
    new Intl.DateTimeFormat("en", { timeZone: timezone }).format();
  } catch {
    throw new Error(`Invalid IANA timezone: ${timezone}`);
  }
}

function fingerprint(scores: ScoreInput[]): string {
  const stable = [...scores]
    .sort((a, b) => a.dimension_id.localeCompare(b.dimension_id))
    .map(({ dimension_id, score, criteria_version_id }) => ({
      dimension_id,
      score,
      criteria_version_id
    }));
  return createHash("sha256").update(JSON.stringify(stable)).digest("hex");
}

export class LeaderboardService {
  constructor(
    private readonly store: RecordStore,
    private readonly clock: Clock = systemClock
  ) {}

  async createLeaderboard(input: {
    name: string;
    timezone: string;
    creator_subject: string;
  }): Promise<Record<string, unknown>> {
    const name = required(input.name, "name");
    const timezone = required(input.timezone, "timezone");
    const creator = required(input.creator_subject, "creator_subject");
    assertTimezone(timezone);
    const id = `lb_${randomUUID()}`;
    const today = localDate(this.clock.now(), timezone);
    const activeFrom = cycleStart(today);
    await this.store.create(TABLES.leaderboards, {
      leaderboard_id: id,
      name,
      timezone,
      cycle_anchor_date: `${activeFrom} 00:00:00`,
      status: "active",
      creator_subject: creator
    });
    for (const dimension of DEFAULT_DIMENSIONS) {
      await this.store.create(TABLES.dimensions, {
        dimension_id: dimension.id,
        leaderboard_id: id,
        name: dimension.name,
        description: dimension.description,
        aggregation: "sum",
        active_from_cycle: `${activeFrom} 00:00:00`,
        is_composite: dimension.id === "thin-muscle",
        composite_definition:
          dimension.id === "thin-muscle" ? "diet:0.5,exercise:0.5" : ""
      });
      await this.store.create(TABLES.criteriaVersions, {
        criteria_version_id: `${id}:${dimension.id}:v1`,
        leaderboard_id: id,
        dimension_id: dimension.id,
        version: 1,
        criteria_text: dimension.criteria,
        policy_status: "confirmed_default",
        effective_from_cycle: `${activeFrom} 00:00:00`,
        created_by: creator
      });
    }
    return this.getDefinition({ leaderboard_id: id });
  }

  async join(input: {
    leaderboard_id: string;
    member_subject: string;
    display_name: string;
  }): Promise<Record<string, unknown>> {
    await this.leaderboard(input.leaderboard_id);
    const memberSubject = required(input.member_subject, "member_subject");
    const displayName = required(input.display_name, "display_name");
    const records = await this.store.list(TABLES.members);
    const existing = records.find(
      (record) =>
        text(record.fields.leaderboard_id) === input.leaderboard_id &&
        text(record.fields.member_subject) === memberSubject
    );
    const now = this.clock.now().toISOString();
    if (existing) {
      if (text(existing.fields.status) !== "active" || text(existing.fields.display_name) !== displayName) {
        await this.store.update(TABLES.members, existing.recordId, {
          ...existing.fields,
          display_name: displayName,
          status: "active",
          joined_at: now,
          left_at: ""
        });
      }
      return { membership_id: text(existing.fields.membership_id), status: "active", idempotent: true };
    }
    const membershipId = `mem_${randomUUID()}`;
    await this.store.create(TABLES.members, {
      membership_id: membershipId,
      leaderboard_id: input.leaderboard_id,
      member_subject: memberSubject,
      display_name: displayName,
      status: "active",
      joined_at: now,
      left_at: ""
    });
    return { membership_id: membershipId, status: "active", idempotent: false };
  }

  async leave(input: { leaderboard_id: string; member_subject: string }): Promise<Record<string, unknown>> {
    const member = await this.member(input.leaderboard_id, input.member_subject, false);
    if (!member || text(member.fields.status) === "left") {
      return { status: "left", idempotent: true };
    }
    await this.store.update(TABLES.members, member.recordId, {
      ...member.fields,
      status: "left",
      left_at: this.clock.now().toISOString()
    });
    return { membership_id: text(member.fields.membership_id), status: "left", idempotent: false };
  }

  async getDefinition(input: { leaderboard_id: string }): Promise<Record<string, unknown>> {
    const leaderboard = await this.leaderboard(input.leaderboard_id);
    const timezone = text(leaderboard.fields.timezone);
    const today = localDate(this.clock.now(), timezone);
    const currentCycle = cycleStart(today);
    const [dimensions, criteria] = await Promise.all([
      this.store.list(TABLES.dimensions),
      this.store.list(TABLES.criteriaVersions)
    ]);
    const activeDimensions = dimensions.filter(
      (record) =>
        text(record.fields.leaderboard_id) === input.leaderboard_id &&
        text(record.fields.active_from_cycle).slice(0, 10) <= currentCycle
    );
    const result = activeDimensions.map((dimension) => {
      const dimensionId = text(dimension.fields.dimension_id);
      const versions = criteria
        .filter(
          (record) =>
            text(record.fields.leaderboard_id) === input.leaderboard_id &&
            text(record.fields.dimension_id) === dimensionId &&
            text(record.fields.effective_from_cycle).slice(0, 10) <= currentCycle
        )
        .sort((a, b) => number(b.fields.version) - number(a.fields.version));
      const current = versions[0];
      if (!current) throw new Error(`No active criteria for dimension ${dimensionId}`);
      return {
        dimension_id: dimensionId,
        name: text(dimension.fields.name),
        description: text(dimension.fields.description),
        aggregation: text(dimension.fields.aggregation),
        is_composite: Boolean(dimension.fields.is_composite),
        composite_definition: text(dimension.fields.composite_definition) || undefined,
        criteria_version_id: text(current.fields.criteria_version_id),
        criteria_version: number(current.fields.version),
        criteria_text: text(current.fields.criteria_text),
        policy_status: text(current.fields.policy_status)
      };
    });
    return {
      leaderboard_id: text(leaderboard.fields.leaderboard_id),
      name: text(leaderboard.fields.name),
      timezone,
      current_local_date: today,
      current_cycle_start: currentCycle,
      next_cycle_start: nextCycleStart(today),
      dimensions: result
    };
  }

  async addDimension(input: {
    leaderboard_id: string;
    actor_subject: string;
    dimension_id: string;
    name: string;
    description: string;
    criteria_text: string;
  }): Promise<Record<string, unknown>> {
    const leaderboard = await this.requireCreator(input.leaderboard_id, input.actor_subject);
    const dimensionId = required(input.dimension_id, "dimension_id");
    const dimensions = await this.store.list(TABLES.dimensions);
    if (
      dimensions.some(
        (record) =>
          text(record.fields.leaderboard_id) === input.leaderboard_id &&
          (text(record.fields.dimension_id) === dimensionId || text(record.fields.name) === input.name)
      )
    ) {
      throw new Error("Dimensions are append-only and this dimension already exists");
    }
    const timezone = text(leaderboard.fields.timezone);
    const effectiveFrom = nextCycleStart(localDate(this.clock.now(), timezone));
    await this.store.create(TABLES.dimensions, {
      dimension_id: dimensionId,
      leaderboard_id: input.leaderboard_id,
      name: required(input.name, "name"),
      description: required(input.description, "description"),
      aggregation: "sum",
      active_from_cycle: `${effectiveFrom} 00:00:00`,
      is_composite: false,
      composite_definition: ""
    });
    const criteriaVersionId = `${input.leaderboard_id}:${dimensionId}:v1`;
    await this.store.create(TABLES.criteriaVersions, {
      criteria_version_id: criteriaVersionId,
      leaderboard_id: input.leaderboard_id,
      dimension_id: dimensionId,
      version: 1,
      criteria_text: required(input.criteria_text, "criteria_text"),
      policy_status: "creator_defined",
      effective_from_cycle: `${effectiveFrom} 00:00:00`,
      created_by: input.actor_subject
    });
    return { dimension_id: dimensionId, criteria_version_id: criteriaVersionId, effective_from_cycle: effectiveFrom };
  }

  async updateCriteria(input: {
    leaderboard_id: string;
    actor_subject: string;
    dimension_id: string;
    criteria_text: string;
  }): Promise<Record<string, unknown>> {
    const leaderboard = await this.requireCreator(input.leaderboard_id, input.actor_subject);
    const dimensions = await this.store.list(TABLES.dimensions);
    if (
      !dimensions.some(
        (record) =>
          text(record.fields.leaderboard_id) === input.leaderboard_id &&
          text(record.fields.dimension_id) === input.dimension_id
      )
    ) {
      throw new Error(`Unknown dimension: ${input.dimension_id}`);
    }
    const criteria = (await this.store.list(TABLES.criteriaVersions)).filter(
      (record) =>
        text(record.fields.leaderboard_id) === input.leaderboard_id &&
        text(record.fields.dimension_id) === input.dimension_id
    );
    const version = Math.max(0, ...criteria.map((record) => number(record.fields.version))) + 1;
    const effectiveFrom = nextCycleStart(localDate(this.clock.now(), text(leaderboard.fields.timezone)));
    const criteriaVersionId = `${input.leaderboard_id}:${input.dimension_id}:v${version}`;
    await this.store.create(TABLES.criteriaVersions, {
      criteria_version_id: criteriaVersionId,
      leaderboard_id: input.leaderboard_id,
      dimension_id: input.dimension_id,
      version,
      criteria_text: required(input.criteria_text, "criteria_text"),
      policy_status: "creator_defined",
      effective_from_cycle: `${effectiveFrom} 00:00:00`,
      created_by: input.actor_subject
    });
    return { criteria_version_id: criteriaVersionId, version, effective_from_cycle: effectiveFrom };
  }

  async submitDailyUpdate(input: {
    leaderboard_id: string;
    member_subject: string;
    idempotency_key: string;
    scores: ScoreInput[];
  }): Promise<Record<string, unknown>> {
    const leaderboard = await this.leaderboard(input.leaderboard_id);
    await this.member(input.leaderboard_id, input.member_subject, true);
    const idempotencyKey = required(input.idempotency_key, "idempotency_key");
    if (idempotencyKey.length > 200) throw new Error("idempotency_key is too long");
    const definition = await this.getDefinition({ leaderboard_id: input.leaderboard_id });
    const dimensions = definition.dimensions as Array<Record<string, unknown>>;
    const expected = new Map(dimensions.map((dimension) => [text(dimension.dimension_id), text(dimension.criteria_version_id)]));
    const seen = new Set<string>();
    for (const score of input.scores) {
      if (seen.has(score.dimension_id)) throw new Error(`Duplicate dimension: ${score.dimension_id}`);
      seen.add(score.dimension_id);
      if (!expected.has(score.dimension_id)) {
        throw new Error(`STALE_CRITERIA: ${score.dimension_id} is not active in the current definition; refresh and recalculate all scores`);
      }
      if (expected.get(score.dimension_id) !== score.criteria_version_id) {
        throw new Error(`STALE_CRITERIA: ${score.dimension_id} must use the current definition; refresh and recalculate all scores`);
      }
      if (!Number.isFinite(score.score) || score.score < 0 || score.score > 100) {
        throw new Error(`Score for ${score.dimension_id} must be between 0 and 100`);
      }
    }
    if (input.scores.length !== expected.size) {
      throw new Error("STALE_CRITERIA: submitted dimensions do not match the current definition; refresh and recalculate all scores");
    }
    const timezone = text(leaderboard.fields.timezone);
    const today = localDate(this.clock.now(), timezone);
    const allScores = await this.store.list(TABLES.dailyScores);
    const todayRows = allScores.filter(
      (record) =>
        text(record.fields.leaderboard_id) === input.leaderboard_id &&
        text(record.fields.member_subject) === input.member_subject &&
        text(record.fields.local_date).slice(0, 10) === today
    );
    const hash = fingerprint(input.scores);
    const sameKey = todayRows.filter((record) => text(record.fields.idempotency_key) === idempotencyKey);
    if (sameKey.length) {
      if (sameKey.every((record) => text(record.fields.submission_hash) === hash)) {
        return { local_date: today, idempotent: true, overwritten: false };
      }
      throw new Error("idempotency_key was already used with different scores");
    }
    const submittedAt = this.clock.now().toISOString();
    for (const score of input.scores) {
      const existing = todayRows.find((record) => text(record.fields.dimension_id) === score.dimension_id);
      const fields = {
        score_snapshot_id: `${input.leaderboard_id}:${input.member_subject}:${today}:${score.dimension_id}`,
        leaderboard_id: input.leaderboard_id,
        member_subject: input.member_subject,
        local_date: `${today} 00:00:00`,
        dimension_id: score.dimension_id,
        score: score.score,
        criteria_version_id: score.criteria_version_id,
        idempotency_key: idempotencyKey,
        submission_hash: hash,
        submitted_at: submittedAt
      };
      if (existing) await this.store.update(TABLES.dailyScores, existing.recordId, fields);
      else await this.store.create(TABLES.dailyScores, fields);
    }
    return { local_date: today, idempotent: false, overwritten: todayRows.length > 0, submitted_at: submittedAt };
  }

  async getLeaderboard(input: {
    leaderboard_id: string;
    period: "day" | "week";
    dimension_id?: string;
  }): Promise<Record<string, unknown>> {
    const leaderboard = await this.leaderboard(input.leaderboard_id);
    const timezone = text(leaderboard.fields.timezone);
    const today = localDate(this.clock.now(), timezone);
    const weekStart = cycleStart(today);
    const dimensionId = input.dimension_id || "thin-muscle";
    const [rows, members] = await Promise.all([
      this.store.list(TABLES.dailyScores),
      this.store.list(TABLES.members)
    ]);
    const totals = new Map<string, number>();
    for (const record of rows) {
      const date = text(record.fields.local_date).slice(0, 10);
      if (
        text(record.fields.leaderboard_id) !== input.leaderboard_id ||
        text(record.fields.dimension_id) !== dimensionId ||
        (input.period === "day" ? date !== today : !inCycle(date, weekStart))
      ) continue;
      const subject = text(record.fields.member_subject);
      totals.set(subject, (totals.get(subject) || 0) + number(record.fields.score));
    }
    const names = new Map(
      members
        .filter((record) => text(record.fields.leaderboard_id) === input.leaderboard_id)
        .map((record) => [text(record.fields.member_subject), text(record.fields.display_name)])
    );
    const sorted = [...totals.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    let lastScore: number | undefined;
    let lastRank = 0;
    const entries = sorted.map(([subject, score], index) => {
      if (score !== lastScore) lastRank = index + 1;
      lastScore = score;
      // member_subject is the caller-chosen identity used for writes; never return it to other readers.
      return { rank: lastRank, display_name: names.get(subject) || "成员", score };
    });
    return {
      leaderboard_id: input.leaderboard_id,
      timezone,
      period: input.period,
      dimension_id: dimensionId,
      date: input.period === "day" ? today : undefined,
      cycle_start: input.period === "week" ? weekStart : undefined,
      scoring: "sum_of_each_day_final_score",
      entries
    };
  }

  private async leaderboard(id: string): Promise<StoredRecord> {
    const record = (await this.store.list(TABLES.leaderboards)).find(
      (item) => text(item.fields.leaderboard_id) === id && text(item.fields.status) === "active"
    );
    if (!record) throw new Error(`Leaderboard not found: ${id}`);
    return record;
  }

  private async requireCreator(id: string, actor: string): Promise<StoredRecord> {
    const leaderboard = await this.leaderboard(id);
    if (text(leaderboard.fields.creator_subject) !== actor) throw new Error("Only the leaderboard creator may change its definition");
    return leaderboard;
  }

  private async member(leaderboardId: string, subject: string, mustBeActive: boolean): Promise<StoredRecord | undefined> {
    const record = (await this.store.list(TABLES.members)).find(
      (item) =>
        text(item.fields.leaderboard_id) === leaderboardId &&
        text(item.fields.member_subject) === subject
    );
    if (mustBeActive && (!record || text(record.fields.status) !== "active")) {
      throw new Error("Member has not joined this leaderboard or has left it");
    }
    return record;
  }
}
