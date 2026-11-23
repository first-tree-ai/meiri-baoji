import * as lark from "@larksuiteoapi/node-sdk";
import { TABLES, type RecordStore, type StoredRecord, type TableName } from "./types.js";

export class MemoryStore implements RecordStore {
  private readonly tables = new Map<TableName, StoredRecord[]>(
    Object.values(TABLES).map((name) => [name, []])
  );
  private sequence = 0;

  async list(table: TableName): Promise<StoredRecord[]> {
    return structuredClone(this.tables.get(table) || []);
  }

  async create(table: TableName, fields: Record<string, unknown>): Promise<StoredRecord> {
    const record = { recordId: `rec_${++this.sequence}`, fields: structuredClone(fields) };
    this.tables.get(table)?.push(record);
    return structuredClone(record);
  }

  async update(table: TableName, recordId: string, fields: Record<string, unknown>): Promise<StoredRecord> {
    const records = this.tables.get(table) || [];
    const index = records.findIndex((record) => record.recordId === recordId);
    if (index < 0) throw new Error(`Record not found: ${recordId}`);
    records[index] = { recordId, fields: structuredClone(fields) };
    return structuredClone(records[index]);
  }
}

interface LarkStoreConfig {
  appId: string;
  appSecret: string;
  baseToken: string;
}

export class LarkBaseStore implements RecordStore {
  private readonly client: any;
  private readonly tableIds = new Map<string, string>();

  constructor(private readonly config: LarkStoreConfig) {
    this.client = new lark.Client({
      appId: config.appId,
      appSecret: config.appSecret,
      appType: lark.AppType.SelfBuild,
      domain: lark.Domain.Feishu
    });
  }

  static fromEnv(env: NodeJS.ProcessEnv = process.env): LarkBaseStore {
    const appId = env.LARK_APP_ID?.trim();
    const appSecret = env.LARK_APP_SECRET?.trim();
    const baseToken = env.LARK_BASE_TOKEN?.trim();
    if (!appId || !appSecret || !baseToken) {
      throw new Error("LARK_APP_ID, LARK_APP_SECRET, and LARK_BASE_TOKEN are required");
    }
    return new LarkBaseStore({ appId, appSecret, baseToken });
  }

  async list(table: TableName): Promise<StoredRecord[]> {
    const tableId = await this.tableId(table);
    const records: StoredRecord[] = [];
    let pageToken: string | undefined;
    do {
      const response = await this.client.bitable.appTableRecord.list({
        path: { app_token: this.config.baseToken, table_id: tableId },
        params: { page_size: 500, page_token: pageToken }
      });
      this.assertSuccess(response);
      for (const item of response.data?.items || []) {
        records.push({ recordId: item.record_id, fields: item.fields || {} });
      }
      pageToken = response.data?.has_more ? response.data?.page_token : undefined;
    } while (pageToken);
    return records;
  }

  async create(table: TableName, fields: Record<string, unknown>): Promise<StoredRecord> {
    const tableId = await this.tableId(table);
    const response = await this.client.bitable.appTableRecord.create({
      path: { app_token: this.config.baseToken, table_id: tableId },
      data: { fields }
    });
    this.assertSuccess(response);
    const record = response.data?.record;
    if (!record?.record_id) throw new Error("Feishu Base did not return a record ID");
    return { recordId: record.record_id, fields: record.fields || fields };
  }

  async update(table: TableName, recordId: string, fields: Record<string, unknown>): Promise<StoredRecord> {
    const tableId = await this.tableId(table);
    const response = await this.client.bitable.appTableRecord.update({
      path: { app_token: this.config.baseToken, table_id: tableId, record_id: recordId },
      data: { fields }
    });
    this.assertSuccess(response);
    const record = response.data?.record;
    return { recordId, fields: record?.fields || fields };
  }

  private async tableId(name: string): Promise<string> {
    const cached = this.tableIds.get(name);
    if (cached) return cached;
    let pageToken: string | undefined;
    do {
      const response = await this.client.bitable.appTable.list({
        path: { app_token: this.config.baseToken },
        params: { page_size: 100, page_token: pageToken }
      });
      this.assertSuccess(response);
      for (const table of response.data?.items || []) {
        if (table.name && table.table_id) this.tableIds.set(table.name, table.table_id);
      }
      pageToken = response.data?.has_more ? response.data?.page_token : undefined;
    } while (pageToken);
    const found = this.tableIds.get(name);
    if (!found) throw new Error(`Feishu Base table not found: ${name}`);
    return found;
  }

  private assertSuccess(response: { code?: number; msg?: string }): void {
    if (response.code && response.code !== 0) {
      throw new Error(`Feishu Base request failed (${response.code}): ${response.msg || "unknown error"}`);
    }
  }
}

export class EnvLarkBaseStore implements RecordStore {
  private inner?: LarkBaseStore;

  private store(): LarkBaseStore {
    this.inner ||= LarkBaseStore.fromEnv();
    return this.inner;
  }

  list(table: TableName): Promise<StoredRecord[]> {
    return this.store().list(table);
  }

  create(table: TableName, fields: Record<string, unknown>): Promise<StoredRecord> {
    return this.store().create(table, fields);
  }

  update(table: TableName, recordId: string, fields: Record<string, unknown>): Promise<StoredRecord> {
    return this.store().update(table, recordId, fields);
  }
}
