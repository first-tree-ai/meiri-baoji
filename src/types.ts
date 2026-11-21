export const TABLES = {
  leaderboards: "Leaderboards",
  dimensions: "Dimensions",
  criteriaVersions: "CriteriaVersions",
  members: "Members",
  dailyScores: "DailyScores"
} as const;

export type TableName = (typeof TABLES)[keyof typeof TABLES];

export interface StoredRecord {
  recordId: string;
  fields: Record<string, unknown>;
}

export interface RecordStore {
  list(table: TableName): Promise<StoredRecord[]>;
  create(table: TableName, fields: Record<string, unknown>): Promise<StoredRecord>;
  update(table: TableName, recordId: string, fields: Record<string, unknown>): Promise<StoredRecord>;
}

export interface Clock {
  now(): Date;
}

export const systemClock: Clock = { now: () => new Date() };

export interface ScoreInput {
  dimension_id: string;
  score: number;
  criteria_version_id: string;
}
