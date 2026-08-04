import type { EntityRef } from "@shiguan/save-schema";

/** 姓+名：王朝（house）名已解析时拼接（如「梁」+「克贞」=「梁克贞」），未解析仅显示名。
 *  王朝以本人命名（如阿拉伯 dynasty founder，house 名 == 名）时不重复拼接。 */
export function displayName(
  name: string,
  dynasty?: EntityRef | null,
): string {
  if (dynasty && dynasty.resolved === true && dynasty.name && dynasty.name !== name) {
    return `${dynasty.name}${name}`;
  }
  return name;
}
