import { describe, it, expect } from "vitest";
import {
  validateProfileEnvelope,
  validateIndexEnvelope,
  isTimelineEvent,
  ContractValidationError,
} from "../contractValidate";
import type { CharacterProfile } from "@shiguan/save-schema";

function validProfileEnv(id: string) {
  return {
    isMock: true,
    source: "fixtures/mock",
    schemaVersion: "1.0",
    generatedFor: "test",
    data: {
      id,
      name: "测试",
      traits: [],
      titles: [],
      residences: [],
      courtPositions: [],
      parents: [],
      spouses: [],
      children: [],
      siblings: [],
      friends: [],
      rivals: [],
      lovers: [],
      wars: [],
      imprisonments: [],
      travels: [],
      memories: [],
      timeline: [
        {
          id: "e1",
          type: "birth",
          title: "出生",
          description: "诞生",
          confidence: "confirmed",
          evidence: [
            {
              id: "v1",
              sourceType: "save_block",
              description: "来源",
              confidence: "confirmed",
            },
          ],
        },
      ],
      evidenceWarnings: [],
    } satisfies CharacterProfile,
  };
}

describe("运行时边界校验（不依赖 TS 类型断言）", () => {
  it("合法 profile 通过校验", () => {
    const p = validateProfileEnvelope(validProfileEnv("abc"), "abc");
    expect(p.id).toBe("abc");
  });

  it("confidence 非法被拒绝", () => {
    const bad = structuredClone(validProfileEnv("abc"));
    // @ts-expect-error 故意注入非法值
    bad.data.timeline[0].confidence = "maybe";
    expect(() => validateProfileEnvelope(bad, "abc")).toThrow(ContractValidationError);
  });

  it("profile id 与请求不一致被拒绝", () => {
    expect(() => validateProfileEnvelope(validProfileEnv("abc"), "other")).toThrow(
      /other/,
    );
  });

  it("index 包 characterIndex 非数组被拒绝", () => {
    const bad = {
      isMock: true,
      source: "fixtures/mock",
      schemaVersion: "1",
      generatedFor: "x",
      data: { meta: {}, characterIndex: {}, profileIds: [] },
    };
    expect(() => validateIndexEnvelope(bad)).toThrow(/characterIndex/);
  });

  it("缺少 isMock 声明被拒绝", () => {
    const bad = {
      source: "fixtures/mock",
      schemaVersion: "1",
      generatedFor: "x",
      data: { meta: {}, characterIndex: [], profileIds: [] },
    };
    expect(() => validateIndexEnvelope(bad)).toThrow(/isMock/);
  });

  it("isTimelineEvent 类型守卫正确", () => {
    expect(isTimelineEvent(validProfileEnv("abc").data.timeline[0])).toBe(true);
    expect(isTimelineEvent({ id: "x" })).toBe(false);
  });

  it("合法 CharacterRef（含 resolved）通过校验", () => {
    const env = validProfileEnv("abc");
    env.data.parents = [
      { id: "p1", name: "赵大", resolved: true, sourcePath: "character/abc/father" },
      { id: "p2", name: "p2", resolved: false },
    ];
    expect(validateProfileEnvelope(env, "abc").parents.length).toBe(2);
  });

  it("CharacterRef.resolved 非 boolean 被拒绝", () => {
    const env = validProfileEnv("abc");
    env.data.children = [{ id: "c1", name: "孩子", resolved: "yes" }];
    expect(() => validateProfileEnvelope(env, "abc")).toThrow(/resolved/);
  });

  it("CharacterRef 缺 name 被拒绝", () => {
    const env = validProfileEnv("abc");
    env.data.siblings = [{ id: "s1" }];
    expect(() => validateProfileEnvelope(env, "abc")).toThrow(/name/);
  });

  it("人物引用列表字段非数组被拒绝", () => {
    const env = validProfileEnv("abc");
    // @ts-expect-error 故意注入非法形状
    env.data.friends = {};
    expect(() => validateProfileEnvelope(env, "abc")).toThrow(/必须是数组/);
  });
});
