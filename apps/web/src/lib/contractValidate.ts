/**
 * 运行时边界校验（不依赖 TypeScript 类型断言）。
 *
 * 契约层（packages/save-schema）定义了形状，但浏览器里 JSON 来自静态文件，
 * 任何损坏 / 串味都会在运行期才暴露。这里在载入 Mock 索引与完整档案时做
 * 真正的结构校验，失败时抛出可读错误，避免页面直接白屏。
 *
 * 覆盖（来自 Phase 1B 要求）：
 *  - isMock === true
 *  - source === "fixtures/mock"
 *  - schemaVersion 存在
 *  - characterIndex 是数组
 *  - profile.id 与请求 id 一致
 *  - timeline 是数组
 *  - 每个 timeline event 有 id / type / confidence / evidence
 *  - confidence 只能是 confirmed / inferred / uncertain
 */
import type {
  CharacterProfile,
  MockIndex,
  TimelineEvent,
} from "@shiguan/save-schema";

export type ValidationIssue =
  | "not_object"
  | "missing_is_mock"
  | "missing_source"
  | "missing_schema_version"
  | "bad_character_index"
  | "bad_profile_ids"
  | "profile_id_mismatch"
  | "bad_timeline"
  | "bad_event_missing_field"
  | "bad_confidence"
  | "bad_evidence"
  | "bad_char_ref_array"
  | "bad_char_ref";

export class ContractValidationError extends Error {
  constructor(public kind: ValidationIssue, message: string) {
    super(message);
    this.name = "ContractValidationError";
  }
}

const CONFIDENCES = new Set(["confirmed", "inferred", "uncertain"]);

function isPlainObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function assertEnvelopeShape(raw: unknown): Record<string, unknown> {
  if (!isPlainObject(raw)) {
    throw new ContractValidationError("not_object", "数据不是合法的对象（期望 FixtureEnvelope）。");
  }
  if (raw.isMock !== true) {
    throw new ContractValidationError(
      "missing_is_mock",
      "Mock 数据必须声明 isMock: true，但当前数据未声明，可能并非可信示例数据。",
    );
  }
  if (raw.source !== "fixtures/mock") {
    throw new ContractValidationError(
      "missing_source",
      `Mock 数据来源应为 "fixtures/mock"，但收到 "${String(raw.source)}"。`,
    );
  }
  if (typeof raw.schemaVersion !== "string" || raw.schemaVersion.length === 0) {
    throw new ContractValidationError(
      "missing_schema_version",
      "Mock 数据缺少 schemaVersion，无法确定契约版本。",
    );
  }
  return raw;
}

function validateTimelineEvent(ev: unknown, index: number): void {
  if (!isPlainObject(ev)) {
    throw new ContractValidationError(
      "bad_event_missing_field",
      `时间线第 ${index + 1} 条不是合法对象。`,
    );
  }
  if (typeof ev.id !== "string" || ev.id.length === 0) {
    throw new ContractValidationError(
      "bad_event_missing_field",
      `时间线第 ${index + 1} 条缺少合法的 id。`,
    );
  }
  if (typeof ev.type !== "string" || ev.type.length === 0) {
    throw new ContractValidationError(
      "bad_event_missing_field",
      `时间线事件 "${ev.id}" 缺少合法的 type。`,
    );
  }
  if (typeof ev.confidence !== "string" || !CONFIDENCES.has(ev.confidence)) {
    throw new ContractValidationError(
      "bad_confidence",
      `时间线事件 "${ev.id}" 的 confidence 非法（应为 confirmed / inferred / uncertain）。`,
    );
  }
  if (!Array.isArray(ev.evidence)) {
    throw new ContractValidationError(
      "bad_evidence",
      `时间线事件 "${ev.id}" 缺少 evidence 证据数组，无法溯源。`,
    );
  }
}

/** CharacterRef 人物引用（父母/子女/兄弟姐妹/好友/宿敌/恋人）结构校验（M5.1）。 */
function validateCharacterRef(ref: unknown, label: string): void {
  if (!isPlainObject(ref)) {
    throw new ContractValidationError("bad_char_ref", `${label} 不是合法对象。`);
  }
  if (typeof ref.id !== "string" || ref.id.length === 0) {
    throw new ContractValidationError(
      "bad_char_ref",
      `${label} 缺少合法的 id。`,
    );
  }
  if (typeof ref.name !== "string") {
    throw new ContractValidationError(
      "bad_char_ref",
      `${label}（id=${String(ref.id)}）缺少合法的 name。`,
    );
  }
  if (ref.resolved !== undefined && typeof ref.resolved !== "boolean") {
    throw new ContractValidationError(
      "bad_char_ref",
      `${label}（id=${String(ref.id)}）的 resolved 必须是 boolean。`,
    );
  }
}

const CHAR_REF_FIELDS = [
  "parents",
  "children",
  "siblings",
  "friends",
  "rivals",
  "lovers",
] as const;

/** 若档案存在人物引用列表字段，则校验其为「合法 CharacterRef 数组」。 */
function validateCharacterRefFields(data: Record<string, unknown>): void {
  for (const key of CHAR_REF_FIELDS) {
    const v = data[key];
    if (v === undefined) continue;
    if (!Array.isArray(v)) {
      throw new ContractValidationError(
        "bad_char_ref_array",
        `档案的 ${key} 必须是数组。`,
      );
    }
    v.forEach((ref, i) => validateCharacterRef(ref, `档案 ${key}[${i}]`));
  }
}

/**
 * 校验 Mock 索引包（FixtureEnvelope<MockIndexPayload>），返回类型化结果。
 * 索引包只应携带轻量摘要 + 档案定位符，不内联完整档案。
 */
export function validateIndexEnvelope(raw: unknown): MockIndex {
  const env = assertEnvelopeShape(raw);
  const data = env.data;
  if (!isPlainObject(data)) {
    throw new ContractValidationError("not_object", "索引包的 data 不是合法对象。");
  }
  if (!Array.isArray(data.characterIndex)) {
    throw new ContractValidationError(
      "bad_character_index",
      "索引包的 characterIndex 必须是数组。",
    );
  }
  if (!Array.isArray(data.profileIds)) {
    throw new ContractValidationError(
      "bad_profile_ids",
      "索引包的 profileIds 必须是数组。",
    );
  }
  // 已校验形状，返回类型化结果交由调用方使用。
  return env as unknown as MockIndex;
}

/**
 * 校验某个完整档案包（FixtureEnvelope<CharacterProfile>），并检查 id 与请求一致。
 */
export function validateProfileEnvelope(
  raw: unknown,
  expectedId: string,
): CharacterProfile {
  const env = assertEnvelopeShape(raw);
  const data = env.data;
  if (!isPlainObject(data)) {
    throw new ContractValidationError("not_object", "档案包的 data 不是合法对象。");
  }
  if (typeof data.id !== "string" || data.id !== expectedId) {
    throw new ContractValidationError(
      "profile_id_mismatch",
      `请求的档案 id 为 "${expectedId}"，但文件中的 id 为 "${String(data.id)}"。`,
    );
  }
  if (!Array.isArray(data.timeline)) {
    throw new ContractValidationError(
      "bad_timeline",
      `档案 "${expectedId}" 的 timeline 必须是数组。`,
    );
  }
  data.timeline.forEach(validateTimelineEvent);
  // M5.1：人物引用列表（父母/子女/兄弟姐妹/好友/宿敌/恋人）结构校验。
  validateCharacterRefFields(data);
  // 返回档案本身（data），而非整个包裹；调用方按 CharacterProfile 使用。
  return data as unknown as CharacterProfile;
}

/** 类型守卫：判断是否为可信的 TimelineEvent（供组件层使用）。 */
export function isTimelineEvent(v: unknown): v is TimelineEvent {
  try {
    validateTimelineEvent(v, 0);
    return true;
  } catch {
    return false;
  }
}
